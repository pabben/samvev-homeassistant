"""Provisioning exercises real private files and synthetic manager API state."""

import argparse
import json
import os
from copy import deepcopy
from unittest.mock import Mock

import pytest

from scripts import provision_connection as pc

BASE_URL = "https://samvev.example.invalid"
HOUSEHOLD = "synthetic-household-one"
OTHER_HOUSEHOLD = "synthetic-household-two"
CONNECTION = "synthetic-ha-connection"
TOKEN = "samvev_it_synthetic_connection_credential"  # noqa: S105
CAPABILITIES = [
    f"ha.{content}.{access}"
    for content in ("groceries", "messages", "calendar")
    for access in ("read", "write")
]


class SyntheticManager:
    """Stateful fake of the existing manager and machine contracts, never a server."""

    def __init__(self) -> None:
        """Start with one selected and one unrelated managed household."""
        self.base_url = BASE_URL
        self.csrf = ""
        self.calls = []
        self.connections = []
        self.people = ["synthetic-reader-b", "synthetic-reader-a"]
        self.sources = ["synthetic-source-b", "synthetic-source-a"]
        self.policy = {
            "revision": 0,
            "listIds": [],
            "household": False,
            "personIds": [],
            "calendarSourceIds": [],
        }
        self.capabilities = list(CAPABILITIES)
        self.identity_changes = {}
        self.fail_policy = False
        self.fail_creation = False
        self.closed = False

    def request(self, method, path, body=None):  # noqa: C901, PLR0911
        """Record allowed household-scoped requests and implement CAS policies."""
        self.calls.append((method, path, deepcopy(body)))
        if path == "/api/v1/auth/login":
            return {"csrfToken": "synthetic-manager-csrf"}
        if path == "/api/v1/me":
            return {
                "memberships": [
                    {
                        "household_id": HOUSEHOLD,
                        "household_name": "Synthetic selected",
                        "capabilities": ["household.manage"],
                    },
                    {
                        "household_id": OTHER_HOUSEHOLD,
                        "household_name": "Synthetic unrelated",
                        "capabilities": ["household.manage"],
                    },
                ]
            }
        base = f"/api/v1/households/{HOUSEHOLD}"
        if path == base + "/people":
            return {
                "people": [
                    {"id": person, "display_name": "Synthetic private name"}
                    for person in self.people
                ]
            }
        if path == base + "/calendar-connections":
            return {
                "connections": [
                    {
                        "disconnectedAt": "2026-01-01T00:00:00Z",
                        "sources": [
                            {
                                "id": source,
                                "name": "Synthetic private source",
                                "enabled": False,
                            }
                            for source in self.sources
                        ],
                    }
                ]
            }
        if path == base + "/integrations" and method == "GET":
            return {"connections": deepcopy(self.connections)}
        if path == base + "/integrations" and method == "POST":
            if self.fail_creation:
                raise pc.ProvisionError("Cannot read a valid response from Samvev")
            self.connections.append(
                {
                    "id": CONNECTION,
                    "name": body["name"],
                    "revision": 1,
                    "revokedAt": None,
                }
            )
            self.capabilities = body["credential"]["capabilities"]
            return {
                "connection": deepcopy(self.connections[-1]),
                "credentialToken": TOKEN,
            }
        if path == base + f"/integrations/{CONNECTION}/ha-sharing":
            if method == "GET":
                return deepcopy(self.policy)
            assert method == "PATCH"
            if self.fail_policy or body["expectedRevision"] != self.policy["revision"]:
                raise pc.ProvisionError("Samvev rejected the request (HTTP 409)")
            self.policy = {
                key: deepcopy(value)
                for key, value in body.items()
                if key != "expectedRevision"
            }
            self.policy["revision"] = body["expectedRevision"] + 1
            return deepcopy(self.policy)
        if path == base + f"/integrations/{CONNECTION}/revoke":
            self.connections[0]["revokedAt"] = "2026-01-01T00:00:00Z"
            return {"connection": deepcopy(self.connections[0])}
        pytest.fail(f"Unexpected synthetic API call: {method} {path}")

    def bearer_connection(self, token):
        """Check the independent bearer identity and expose confirmed current grants."""
        self.calls.append(("BEARER", "/api/v1/ha/connection", None))
        if token != TOKEN:
            raise pc.ProvisionError("Samvev rejected the request (HTTP 401)")
        return {
            "schemaVersion": 1,
            "installationId": "synthetic-installation",
            "connectionId": CONNECTION,
            "householdId": HOUSEHOLD,
            "capabilities": self.capabilities,
            "grants": deepcopy(self.policy),
            **self.identity_changes,
        }

    def close(self):
        """Record temporary manager logout for CLI failure tests."""
        self.closed = True


def options(tmp_path, **changes):
    """Select the complete, explicitly authorized household policy."""
    return argparse.Namespace(
        **{
            "url": BASE_URL,
            "email": "manager@example.invalid",
            "household": HOUSEHOLD,
            "name": "Samvev HA",
            "inspect": False,
            "share_groceries": True,
            "write_groceries": True,
            "messages": True,
            "write_messages": True,
            "calendar": True,
            "write_calendar": True,
            "share_household": True,
            "person": [],
            "calendar_source": [],
            "all_current_persons": True,
            "all_current_calendar_sources": True,
            "allow_shared_native_writes": True,
            "reuse_existing": True,
            "output": tmp_path / "private-connection.json",
            **changes,
        }
    )


@pytest.fixture
def password(monkeypatch):
    """Never prompt for real credentials during tests."""
    monkeypatch.setattr(pc.getpass, "getpass", lambda _: "synthetic-password")


def writes(manager):
    """Return connection/policy mutations, excluding the temporary manager login."""
    return [
        call
        for call in manager.calls
        if call[0] in {"POST", "PATCH", "DELETE"} and "/integrations" in call[1]
    ]


def test_create_then_reuse_exact_identity_and_private_file(tmp_path, password, capsys):
    """Second execution keeps one connection/token and performs no redundant CAS."""
    manager = SyntheticManager()
    args = options(tmp_path)
    pc.provision(args, manager)
    saved = pc.read_secret(args.output)
    assert saved["api_token"] == TOKEN
    assert saved["installation_id"] == "synthetic-installation"
    assert args.output.stat().st_mode & 0o777 == 0o600
    assert manager.capabilities == CAPABILITIES
    assert manager.policy == {
        "revision": 1,
        "listIds": ["groceries"],
        "household": True,
        "personIds": sorted(manager.people),
        "calendarSourceIds": sorted(manager.sources),
        "allowSharedNativeWrites": True,
    }
    original_bytes = args.output.read_bytes()
    original_inode = args.output.stat().st_ino
    manager.calls.clear()
    pc.provision(args, manager)
    assert writes(manager) == []
    assert len(manager.connections) == 1
    assert args.output.read_bytes() == original_bytes
    assert args.output.stat().st_ino == original_inode
    out = capsys.readouterr()
    assert out.out == f"{args.output}\n{args.output}\n"
    assert not out.err
    assert TOKEN not in out.out
    assert "Synthetic private" not in out.out
    assert HOUSEHOLD not in out.out
    assert CONNECTION not in out.out
    assert all(OTHER_HOUSEHOLD not in call[1] for call in manager.calls)


def test_explicit_current_selection_updates_once_without_token_rotation(
    tmp_path, password
):
    """All-current switches snapshot current IDs only when the command runs again."""
    manager, args = SyntheticManager(), options(tmp_path)
    pc.provision(args, manager)
    old_token = pc.read_secret(args.output)["api_token"]
    manager.people.append("synthetic-new-reader")
    manager.sources.append("synthetic-new-source")
    assert "synthetic-new-reader" not in manager.policy["personIds"]
    assert "synthetic-new-source" not in manager.policy["calendarSourceIds"]
    manager.calls.clear()
    pc.provision(args, manager)
    assert len(writes(manager)) == 1
    method, _, body = writes(manager)[0]
    assert method == "PATCH"
    assert body["expectedRevision"] == 1
    assert manager.policy["revision"] == 2
    assert manager.policy["personIds"] == sorted(manager.people)
    assert manager.policy["calendarSourceIds"] == sorted(manager.sources)
    assert pc.read_secret(args.output)["api_token"] == old_token
    assert not any("/credentials" in call[1] for call in manager.calls)


def test_cas_conflict_does_not_overwrite_or_revoke_reused_connection(
    tmp_path, password
):
    """Concurrent admin edits require review, never blind retries or blanket revoke."""
    manager, args = SyntheticManager(), options(tmp_path)
    pc.provision(args, manager)
    manager.calls.clear()
    manager.people.append("synthetic-new-reader")
    manager.fail_policy = True
    with pytest.raises(pc.ProvisionError, match="409"):
        pc.provision(args, manager)
    assert len(writes(manager)) == 1
    assert writes(manager)[0][0] == "PATCH"
    assert manager.connections[0]["revokedAt"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "https://other.example.invalid"},
        {"household_id": OTHER_HOUSEHOLD},
        {"connection_id": "other-connection"},
        {"installation_id": "other-installation"},
        {"api_token": "revoked-synthetic-token"},
    ],
)
def test_wrong_identity_or_revoked_credential_cannot_mutate(tmp_path, password, change):
    """Stored metadata is insufficient; the independent bearer identity must agree."""
    manager, args = SyntheticManager(), options(tmp_path)
    pc.provision(args, manager)
    saved = pc.read_secret(args.output)
    saved.update(change)
    args.output.write_text(json.dumps(saved))
    manager.calls.clear()
    with pytest.raises(pc.ProvisionError):
        pc.provision(args, manager)
    assert writes(manager) == []
    assert manager.connections[0]["revokedAt"] is None


def test_capability_change_never_automatically_rotates_token(tmp_path, password):
    """Changed credential capabilities fail before policy edits or rotation."""
    manager, args = SyntheticManager(), options(tmp_path)
    pc.provision(args, manager)
    manager.capabilities = ["ha.groceries.read"]
    manager.calls.clear()
    with pytest.raises(pc.ProvisionError, match="rotation"):
        pc.provision(args, manager)
    assert writes(manager) == []


def test_existing_output_requires_explicit_reuse(tmp_path, password):
    """An accidental rerun of the old command cannot create a duplicate."""
    manager, args = SyntheticManager(), options(tmp_path)
    pc.provision(args, manager)
    args.reuse_existing = False
    manager.calls.clear()
    with pytest.raises(pc.ProvisionError, match="reuse-existing"):
        pc.provision(args, manager)
    assert manager.calls == []


def test_active_name_without_private_file_blocks_duplicate(tmp_path, password):
    """Never guess identity by name or silently replace a lost credential."""
    manager, args = SyntheticManager(), options(tmp_path)
    manager.connections = [{"id": CONNECTION, "name": args.name, "revokedAt": None}]
    with pytest.raises(pc.ProvisionError, match="recover"):
        pc.provision(args, manager)
    assert writes(manager) == []
    assert not args.output.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [("person", ["foreign-reader"]), ("calendar_source", ["foreign-source"])],
)
def test_foreign_household_selection_rejected_before_connection_creation(
    tmp_path, password, field, value
):
    """All-current selection cannot smuggle manually supplied foreign IDs."""
    manager, args = SyntheticManager(), options(tmp_path, **{field: value})
    with pytest.raises(pc.ProvisionError, match="outside this household"):
        pc.provision(args, manager)
    assert writes(manager) == []


def test_file_failure_revokes_only_the_new_connection(tmp_path, password, monkeypatch):
    """Failed one-time secret persistence must not leave an active forgotten token."""
    manager, args = SyntheticManager(), options(tmp_path)
    monkeypatch.setattr(
        pc, "write_secret", Mock(side_effect=OSError("synthetic disk failure"))
    )
    with pytest.raises(OSError, match="synthetic disk failure"):
        pc.provision(args, manager)
    assert manager.connections[0]["revokedAt"] is not None
    assert len([call for call in writes(manager) if call[1].endswith("/revoke")]) == 1


def test_ambiguous_create_is_not_retried(tmp_path, password):
    """A lost create response needs metadata reconciliation, not a duplicate POST."""
    manager, args = SyntheticManager(), options(tmp_path)
    manager.fail_creation = True
    with pytest.raises(pc.ProvisionError):
        pc.provision(args, manager)
    assert len(writes(manager)) == 1
    assert writes(manager)[0][0] == "POST"


@pytest.mark.parametrize(
    "kind",
    ["permissions", "symlink", "hardlink", "invalid_json", "oversize", "directory"],
)
def test_unsafe_existing_private_file_prevents_any_network_requests(tmp_path, kind):
    """Reject unsafe targets before obtaining an administrator session."""
    manager, args = SyntheticManager(), options(tmp_path)
    if kind == "directory":
        args.output.mkdir()
    elif kind == "symlink":
        target = tmp_path / "target"
        target.write_text("{}")
        args.output.symlink_to(target)
    else:
        args.output.write_text(
            "{"
            if kind == "invalid_json"
            else "x" * (pc.MAX_SECRET_BYTES + 1)
            if kind == "oversize"
            else "{}"
        )
        args.output.chmod(0o644 if kind == "permissions" else 0o600)
        if kind == "hardlink":
            os.link(args.output, tmp_path / "linked-credential")
    with pytest.raises((pc.ProvisionError, OSError)):
        pc.provision(args, manager)
    assert manager.calls == []


def test_local_output_lock_serializes_creators(tmp_path):
    """The same output cannot be provisioned concurrently by local processes."""
    manager, args = SyntheticManager(), options(tmp_path)
    with (
        pc._output_lock(args.output),  # noqa: SLF001
        pytest.raises(pc.ProvisionError, match="Another provisioning"),
    ):
        pc.provision(args, manager)
    assert manager.calls == []


def test_bearer_validation_never_sends_manager_cookie_or_csrf(monkeypatch):
    """The config credential is validated as a distinct machine identity."""
    captured = []

    def response(opener, request):
        captured.append((opener, request))
        return {"schemaVersion": 1}

    manager = pc.ManagerSession(BASE_URL)
    manager.csrf = "synthetic-manager-csrf"
    monkeypatch.setattr(pc, "_read_response", response)
    manager.bearer_connection(TOKEN)
    opener, request = captured[0]
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert request.get_header("Cookie") is None
    assert request.get_header("X-csrf-token") is None
    assert request.get_header("Origin") is None
    assert not any(
        isinstance(handler, pc.urllib.request.HTTPCookieProcessor)
        for handler in opener.handlers
    )


def test_main_failure_never_prints_underlying_secrets(
    tmp_path, password, monkeypatch, capsys
):
    """CLI errors and logout remain sanitized even if filesystem errors contain data."""
    manager, args = SyntheticManager(), options(tmp_path)
    monkeypatch.setattr(pc, "arguments", lambda: args)
    monkeypatch.setattr(pc, "ManagerSession", lambda _: manager)
    monkeypatch.setattr(pc, "write_secret", Mock(side_effect=OSError(TOKEN)))
    assert pc.main() == 1
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err
    assert "synthetic-password" not in out.out + out.err
    assert manager.closed


def test_legacy_groceries_only_command_omits_new_policy_field(tmp_path, password):
    """Default-false remains compatible with the existing migration 047 server."""
    manager = SyntheticManager()
    args = options(
        tmp_path,
        messages=False,
        write_messages=False,
        calendar=False,
        write_calendar=False,
        share_household=False,
        all_current_persons=False,
        all_current_calendar_sources=False,
        allow_shared_native_writes=False,
    )
    pc.provision(args, manager)
    patch = next(call for call in writes(manager) if call[0] == "PATCH")
    assert "allowSharedNativeWrites" not in patch[2]
    assert manager.capabilities == ["ha.groceries.read", "ha.groceries.write"]
    assert pc.read_secret(args.output)["api_token"] == TOKEN


def test_all_current_flags_are_opt_in_and_do_not_enable_imported_sources(
    tmp_path, password
):
    """Existing private selections stay explicit; source settings are never changed."""
    manager = SyntheticManager()
    args = options(
        tmp_path, all_current_persons=False, all_current_calendar_sources=False
    )
    pc.provision(args, manager)
    assert manager.policy["personIds"] == []
    assert manager.policy["calendarSourceIds"] == []
    assert all("calendar-connections" not in call[1] for call in manager.calls)
    assert all("/people" not in call[1] for call in manager.calls)


def test_wrong_file_owner_and_unsafe_lock_fail_closed(tmp_path, monkeypatch):
    """Another owner's credential and a symlinked lock cannot be reused."""
    args = options(tmp_path)
    pc.write_secret(
        args.output,
        {
            "base_url": BASE_URL,
            "api_token": TOKEN,
            "household_id": HOUSEHOLD,
            "connection_id": CONNECTION,
        },
    )
    with monkeypatch.context() as context:
        context.setattr(pc.os, "getuid", lambda: args.output.stat().st_uid + 1)
        with pytest.raises(pc.ProvisionError, match="owner-owned"):
            pc.read_secret(args.output)
    target = tmp_path / "unrelated"
    target.write_text("unchanged")
    lock = args.output.with_name(f".{args.output.name}.lock")
    lock.symlink_to(target)
    manager = SyntheticManager()
    with pytest.raises(OSError, match="symbolic"):
        pc.provision(args, manager)
    assert target.read_text() == "unchanged"
    assert manager.calls == []


def test_cli_parses_reuse_and_static_selection_flags(tmp_path, monkeypatch):
    """The documented argument names reach the implementation unchanged."""
    monkeypatch.setattr(
        pc.sys,
        "argv",
        [
            "provision_connection.py",
            "--url",
            BASE_URL,
            "--email",
            "manager@example.invalid",
            "--output",
            str(tmp_path / "secret.json"),
            "--reuse-existing",
            "--all-current-persons",
            "--all-current-calendar-sources",
            "--allow-shared-native-writes",
        ],
    )
    args = pc.arguments()
    assert args.reuse_existing
    assert args.all_current_persons
    assert args.all_current_calendar_sources
    assert args.allow_shared_native_writes
