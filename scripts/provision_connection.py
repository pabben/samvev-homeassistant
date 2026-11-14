"""Create or reuse an explicitly scoped HA credential using a manager login.

Uses Python's standard library on Unix. Passwords and sessions remain in memory;
credentials stay in an owner-only local file and are never printed.
"""
# ruff: noqa: T201 -- Interactive operator command; never a logger.

from __future__ import annotations

import argparse
import fcntl
import getpass
import http.cookiejar
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

MAX_RESPONSE_BYTES = 2_000_000
MAX_SECRET_BYTES = 16_384
PRIVATE_MODE = 0o600
MAX_POLICY_IDS = 50


class ProvisionError(Exception):
    """An intentionally sanitized provisioning failure."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward authorization to a redirect destination."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        """Reject every redirect."""
        raise ProvisionError("Redirect refused; enter the final Samvev URL")


def _read_response(opener: Any, request: urllib.request.Request) -> dict[str, Any]:  # noqa: ANN401
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ProvisionError("Response exceeds the size limit")
            value = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raise ProvisionError(
            f"Samvev rejected the request (HTTP {error.code})"
        ) from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise ProvisionError("Cannot read a valid response from Samvev") from None
    if not isinstance(value, dict):
        raise ProvisionError("Unexpected Samvev response")
    return value


class ManagerSession:
    """Temporary manager session; never reused as the machine identity."""

    def __init__(self, base_url: str) -> None:
        """Validate the URL and create an in-memory cookie jar."""
        parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ProvisionError("Enter an HTTP(S) URL without credentials or query")
        self.base_url = base_url.rstrip("/")
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPCookieProcessor(self.cookies)
        )
        self.csrf = ""

    def request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make one manager request without logging credentials or content."""
        headers = {"Accept": "application/json", "Origin": self.origin}
        if self.csrf:
            headers["x-csrf-token"] = self.csrf
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = urllib.request.Request(  # noqa: S310
            self.base_url + path, data=data, headers=headers, method=method
        )
        return _read_response(self.opener, request)

    def bearer_connection(self, token: str) -> dict[str, Any]:
        """Validate the saved machine credential without manager cookies or CSRF."""
        request = urllib.request.Request(  # noqa: S310
            self.base_url + "/api/v1/ha/connection",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            method="GET",
        )
        return _read_response(urllib.request.build_opener(NoRedirect()), request)

    def close(self) -> None:
        """Revoke the temporary manager session and discard its cookies."""
        try:
            if self.csrf:
                self.request("POST", "/api/v1/auth/logout", {})
        finally:
            self.cookies.clear()
            self.csrf = ""


def _check_private_file(descriptor: int) -> None:
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != PRIVATE_MODE
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
    ):
        raise ProvisionError("Use a regular, owner-owned, single-link mode 0600 file")


@contextmanager
def _output_lock(path: Path) -> Iterator[None]:
    """Serialize local runs for the same output without following lock symlinks."""
    lock_path = path.with_name(f".{path.name}.lock")
    descriptor = os.open(
        lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
    )
    try:
        _check_private_file(descriptor)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ProvisionError(
                "Another provisioning run uses this output file"
            ) from None
        yield
    finally:
        os.close(descriptor)


def read_secret(path: Path) -> dict[str, Any] | None:
    """Read a bounded, existing private file without following links or FIFOs."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        _check_private_file(descriptor)
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(MAX_SECRET_BYTES + 1)
        if len(raw) > MAX_SECRET_BYTES:
            raise ProvisionError("Private credential file exceeds the size limit")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ProvisionError("Private credential file is not valid JSON") from None
        if not isinstance(value, dict) or any(
            not isinstance(value.get(key), str) or not value[key]
            for key in ("base_url", "api_token", "connection_id", "household_id")
        ):
            raise ProvisionError("Private credential file has missing fields")
        return value
    finally:
        os.close(descriptor)


def write_secret(path: Path, content: dict[str, Any]) -> None:
    """Exclusively create and sync an owner-only credential file."""
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    try:
        _check_private_file(descriptor)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
            json.dump(content, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def arguments() -> argparse.Namespace:
    """Parse explicit sharing choices; future people/sources are never auto-shared."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--household", help="Required for several managed households")
    parser.add_argument("--name", default="Samvev HA")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="List household/person/source IDs and names; creates no credential",
    )
    parser.add_argument("--share-groceries", action="store_true")
    parser.add_argument("--share-household", action="store_true")
    parser.add_argument(
        "--person",
        action="append",
        default=[],
        help="Reader person UUID; repeat as needed",
    )
    parser.add_argument(
        "--calendar-source",
        action="append",
        default=[],
        help="Imported source UUID; repeat as needed",
    )
    parser.add_argument(
        "--all-current-persons",
        action="store_true",
        help="Select all current household people; a static snapshot",
    )
    parser.add_argument(
        "--all-current-calendar-sources",
        action="store_true",
        help="Select all current household source IDs, without enabling sources",
    )
    parser.add_argument(
        "--allow-shared-native-writes",
        action="store_true",
        help="Allow shared native writes; requires backend migration 048",
    )
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Reuse the saved credential; never rotate or create duplicate connections",
    )
    parser.add_argument("--messages", action="store_true")
    parser.add_argument("--calendar", action="store_true")
    parser.add_argument("--write-groceries", action="store_true")
    parser.add_argument("--write-messages", action="store_true")
    parser.add_argument("--write-calendar", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        help="Owner-only JSON file; required except with --inspect",
    )
    result = parser.parse_args()
    if not result.inspect and result.output is None:
        parser.error("--output is required")
    return result


def _capabilities(args: argparse.Namespace) -> list[str]:
    capabilities = []
    for content, readable, writable in (
        ("groceries", args.share_groceries, args.write_groceries),
        ("messages", args.messages, args.write_messages),
        ("calendar", args.calendar, args.write_calendar),
    ):
        if writable and not readable:
            raise ProvisionError(f"Select read sharing before --write-{content}")
        if readable:
            capabilities.append(f"ha.{content}.read")
        if writable:
            capabilities.append(f"ha.{content}.write")
    if not capabilities:
        raise ProvisionError("Select at least one content type")
    if getattr(args, "allow_shared_native_writes", False) and not (
        args.write_messages or args.write_calendar
    ):
        raise ProvisionError("Select native write capabilities before shared writes")
    return capabilities


def _policy(
    args: argparse.Namespace, session: ManagerSession, household_id: str
) -> dict[str, Any]:
    people = set(args.person)
    sources = set(args.calendar_source)
    base = f"/api/v1/households/{household_id}"
    if people or getattr(args, "all_current_persons", False):
        available_people = {
            row["id"] for row in session.request("GET", base + "/people")["people"]
        }
        if not people <= available_people:
            raise ProvisionError("A selected person is outside this household")
        if getattr(args, "all_current_persons", False):
            people.update(available_people)
    if sources or getattr(args, "all_current_calendar_sources", False):
        connections = session.request("GET", base + "/calendar-connections")[
            "connections"
        ]
        available_sources = {
            source["id"]
            for connection in connections
            for source in connection["sources"]
        }
        if not sources <= available_sources:
            raise ProvisionError("A selected calendar source is outside this household")
        if getattr(args, "all_current_calendar_sources", False):
            sources.update(available_sources)
    if len(people) > MAX_POLICY_IDS or len(sources) > MAX_POLICY_IDS:
        raise ProvisionError(
            "This sharing API supports at most 50 people and 50 sources"
        )
    if (args.messages or args.calendar) and not (args.share_household or people):
        raise ProvisionError("Select household and/or explicit person readers")
    return {
        "listIds": ["groceries"] if args.share_groceries else [],
        "household": args.share_household,
        "personIds": sorted(people),
        "calendarSourceIds": sorted(sources),
        "allowSharedNativeWrites": getattr(args, "allow_shared_native_writes", False),
    }


def _normalized_policy(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "listIds": sorted(value.get("listIds", [])),
        "household": value.get("household", False),
        "personIds": sorted(value.get("personIds", [])),
        "calendarSourceIds": sorted(value.get("calendarSourceIds", [])),
        "allowSharedNativeWrites": value.get("allowSharedNativeWrites", False),
    }


def _set_policy(
    session: ManagerSession, base: str, connection_id: str, desired: dict[str, Any]
) -> None:
    current = session.request("GET", f"{base}/{connection_id}/ha-sharing")
    if _normalized_policy(current) == desired:
        return
    payload = {**desired, "expectedRevision": current["revision"]}
    if (
        not desired["allowSharedNativeWrites"]
        and "allowSharedNativeWrites" not in current
    ):
        payload.pop(
            "allowSharedNativeWrites"
        )  # Keep default-false compatibility with migration 047.
    updated = session.request("PATCH", f"{base}/{connection_id}/ha-sharing", payload)
    if _normalized_policy(updated) != desired:
        raise ProvisionError("Samvev did not confirm the requested sharing policy")


def _reject_unconfirmed_sharing() -> None:
    raise ProvisionError("Machine authorization did not confirm the requested sharing")


def _validate_machine(
    session: ManagerSession,
    secret: dict[str, Any],
    household_id: str,
    capabilities: list[str],
) -> dict[str, Any]:
    if (
        secret["base_url"].rstrip("/") != session.base_url
        or secret["household_id"] != household_id
    ):
        raise ProvisionError("Saved credential belongs to another URL or household")
    identity = session.bearer_connection(secret["api_token"])
    if (
        type(identity.get("schemaVersion")) is not int
        or identity.get("schemaVersion") != 1
        or identity.get("householdId") != household_id
        or identity.get("connectionId") != secret["connection_id"]
        or not isinstance(identity.get("installationId"), str)
        or not identity.get("installationId")
        or (
            secret.get("installation_id")
            and identity["installationId"] != secret["installation_id"]
        )
    ):
        raise ProvisionError("Saved credential connection identity does not match")
    actual_capabilities = identity.get("capabilities")
    if (
        not isinstance(actual_capabilities, list)
        or any(not isinstance(value, str) for value in actual_capabilities)
        or len(actual_capabilities) != len(capabilities)
        or set(actual_capabilities) != set(capabilities)
    ):
        raise ProvisionError(
            "Saved credential capabilities differ; automatic rotation is disabled"
        )
    return identity


def _inspect(session: ManagerSession, memberships: list[dict[str, Any]]) -> None:
    for row in memberships:
        household_id = row["household_id"]
        print(f"Household {household_id}: {row['household_name']}")
        people = session.request("GET", f"/api/v1/households/{household_id}/people")
        for person in people["people"]:
            print(f"Reader person {person['id']}: {person['display_name']}")
        calendars = session.request(
            "GET", f"/api/v1/households/{household_id}/calendar-connections"
        )
        for connection in calendars["connections"]:
            for source in connection["sources"]:
                print(f"Calendar source {source['id']}: {source['name']}")


def _provision(args: argparse.Namespace, session: ManagerSession) -> None:  # noqa: C901
    saved = None if args.inspect else read_secret(args.output)
    if saved and not getattr(args, "reuse_existing", False):
        raise ProvisionError(
            "Output already exists; use --reuse-existing to validate and reuse it"
        )
    if saved and saved["base_url"].rstrip("/") != session.base_url:
        raise ProvisionError("Saved credential belongs to another URL")
    if saved and args.household and saved["household_id"] != args.household:
        raise ProvisionError("Saved credential belongs to another household")
    login = session.request(
        "POST",
        "/api/v1/auth/login",
        {
            "email": args.email,
            "password": getpass.getpass("Samvev manager password: "),
        },
    )
    session.csrf = login["csrfToken"]
    me = session.request("GET", "/api/v1/me")
    memberships = [
        row for row in me["memberships"] if "household.manage" in row["capabilities"]
    ]
    selected_household = args.household or (saved["household_id"] if saved else None)
    if selected_household:
        memberships = [
            row for row in memberships if row["household_id"] == selected_household
        ]
    if args.inspect:
        _inspect(session, memberships)
        return
    if len(memberships) != 1:
        raise ProvisionError("Select exactly one managed household using --household")
    household_id = memberships[0]["household_id"]
    capabilities = _capabilities(args)
    desired = _policy(args, session, household_id)
    base = f"/api/v1/households/{household_id}/integrations"
    if saved:
        _validate_machine(session, saved, household_id, capabilities)
        _set_policy(session, base, saved["connection_id"], desired)
        # Revalidate after any manager mutation; never rotate or rewrite this file.
        identity = _validate_machine(session, saved, household_id, capabilities)
        if _normalized_policy(identity.get("grants", {})) != desired:
            _reject_unconfirmed_sharing()
        print(args.output)
        return
    existing = session.request("GET", base)["connections"]
    if any(
        row.get("name") == args.name and row.get("revokedAt") is None
        for row in existing
    ):
        raise ProvisionError(
            "An active connection already has this name; "
            "recover its private credential instead of creating a duplicate"
        )
    created = session.request(
        "POST",
        base,
        {
            "name": args.name,
            "displayIds": [],
            "credential": {
                "name": args.name,
                "capabilities": capabilities,
                "expiresAt": None,
            },
        },
    )
    connection = created["connection"]
    try:
        _set_policy(session, base, connection["id"], desired)
        secret = {
            "base_url": session.base_url,
            "api_token": created["credentialToken"],
            "connection_id": connection["id"],
            "household_id": household_id,
        }
        identity = _validate_machine(session, secret, household_id, capabilities)
        if _normalized_policy(identity.get("grants", {})) != desired:
            _reject_unconfirmed_sharing()
        secret["installation_id"] = identity["installationId"]
        write_secret(args.output, secret)
    except (ProvisionError, OSError, KeyError, ValueError):
        # Never revoke a reused connection. Only this newly created connection is ours.
        try:
            session.request(
                "POST",
                f"{base}/{connection['id']}/revoke",
                {"expectedRevision": connection["revision"]},
            )
        except ProvisionError:
            print(
                "Incomplete connection needs manager review; no credential printed.",
                file=sys.stderr,
            )
        raise
    print(args.output)


def provision(args: argparse.Namespace, session: ManagerSession) -> None:
    """Create once or reuse the saved identity under a local exclusive lock."""
    if args.inspect:
        _provision(args, session)
    else:
        with _output_lock(args.output):
            _provision(args, session)


def main() -> int:
    """Run without printing credentials, content or underlying exception bodies."""
    args = arguments()
    session: ManagerSession | None = None
    try:
        session = ManagerSession(args.url)
        provision(args, session)
    except ProvisionError as error:
        print(f"Provisioning failed: {error}", file=sys.stderr)
        return 1
    except (OSError, KeyError, ValueError, TypeError):
        print(
            "Provisioning failed; check the private file and server response.",
            file=sys.stderr,
        )
        return 1
    finally:
        if session:
            try:
                session.close()
            except ProvisionError:
                print(
                    "Temporary session logout could not be confirmed.", file=sys.stderr
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
