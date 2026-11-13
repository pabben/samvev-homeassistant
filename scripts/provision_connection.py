"""Create an explicitly scoped HA credential using a temporary manager login.

Uses only Python's standard library. The password and session remain in memory;
the one-time integration token is written to a new owner-only file, never stdout.
"""
# ruff: noqa: T201 -- This is an interactive command-line tool, never a logger.

from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MAX_RESPONSE_BYTES = 2_000_000


class ProvisionError(Exception):
    """An intentionally sanitized provisioning failure."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward a manager session to a redirect destination."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        """Reject every redirect."""
        raise ProvisionError("Redirect refused; enter the final Samvev URL")


class ManagerSession:
    """Short-lived browser-protocol session used only to provision a credential."""

    def __init__(self, base_url: str) -> None:
        """Validate the URL and create an in-memory cookie jar."""
        parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
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
        """Make one request; do not log response bodies, tokens or cookies."""
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
        try:
            with self.opener.open(request, timeout=15) as response:
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

    def close(self) -> None:
        """Revoke the temporary session and discard its cookies."""
        try:
            if self.csrf:
                self.request("POST", "/api/v1/auth/logout", {})
        finally:
            self.cookies.clear()
            self.csrf = ""


def write_secret(path: Path, content: dict[str, Any]) -> None:
    """Exclusively create an owner-only credential file without following links."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2)
        handle.write("\n")


def arguments() -> argparse.Namespace:
    """Parse an explicit, deny-by-default sharing policy."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--household", help="Required when the manager has several households"
    )
    parser.add_argument("--name", default="Samvev HA")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="List household/person/source IDs without creating a credential",
    )
    parser.add_argument("--share-groceries", action="store_true")
    parser.add_argument(
        "--share-household",
        action="store_true",
        help="Allow household-addressed messages and native events",
    )
    parser.add_argument(
        "--person",
        action="append",
        default=[],
        help="Explicit reader person UUID; repeat as needed",
    )
    parser.add_argument(
        "--calendar-source",
        action="append",
        default=[],
        help="Existing imported source UUID; repeat as needed",
    )
    parser.add_argument("--messages", action="store_true")
    parser.add_argument("--calendar", action="store_true")
    parser.add_argument("--write-groceries", action="store_true")
    parser.add_argument("--write-messages", action="store_true")
    parser.add_argument("--write-calendar", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        help="New owner-only JSON file; required except with --inspect",
    )
    result = parser.parse_args()
    if not result.inspect and result.output is None:
        parser.error("--output is required")
    return result


def provision(args: argparse.Namespace, session: ManagerSession) -> None:  # noqa: C901, PLR0912
    """Resolve the selected household, then create grants and a bearer token."""
    login = session.request(
        "POST",
        "/api/v1/auth/login",
        {"email": args.email, "password": getpass.getpass("Samvev manager password: ")},
    )
    session.csrf = login["csrfToken"]
    me = session.request("GET", "/api/v1/me")
    memberships = [
        row for row in me["memberships"] if "household.manage" in row["capabilities"]
    ]
    if args.household:
        memberships = [
            row for row in memberships if row["household_id"] == args.household
        ]
    if args.inspect:
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
        return
    if len(memberships) != 1:
        raise ProvisionError(
            "Select exactly one managed household using --household; use --inspect"
        )
    capabilities: list[str] = []
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
    if (args.messages or args.calendar) and not (args.share_household or args.person):
        raise ProvisionError(
            "Select --share-household and/or explicit --person readers"
        )
    household_id = memberships[0]["household_id"]
    base = f"/api/v1/households/{household_id}/integrations"
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
        session.request(
            "PATCH",
            f"{base}/{connection['id']}/ha-sharing",
            {
                "expectedRevision": 0,
                "listIds": ["groceries"] if args.share_groceries else [],
                "household": args.share_household,
                "personIds": args.person,
                "calendarSourceIds": args.calendar_source,
            },
        )
        write_secret(
            args.output,
            {
                "base_url": session.base_url,
                "api_token": created["credentialToken"],
                "connection_id": connection["id"],
                "household_id": household_id,
            },
        )
    except (ProvisionError, OSError):
        # A failed setup must not leave a forgotten active machine credential.
        try:
            session.request(
                "POST",
                f"{base}/{connection['id']}/revoke",
                {"expectedRevision": connection["revision"]},
            )
        except ProvisionError:
            print(
                f"Revoke incomplete connection {connection['id']} in Samvev.",
                file=sys.stderr,
            )
        raise
    print(
        f"Created connection {connection['id']}. "
        f"Credential saved to {args.output} (mode 0600)."
    )


def main() -> int:
    """Run provisioning without disclosing failures or secrets in tracebacks."""
    args = arguments()
    session: ManagerSession | None = None
    try:
        session = ManagerSession(args.url)
        provision(args, session)
    except (ProvisionError, OSError, KeyError, ValueError) as error:
        print(f"Provisioning failed: {error}", file=sys.stderr)
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
