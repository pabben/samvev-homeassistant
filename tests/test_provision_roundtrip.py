"""Exercise provisioning against the actual isolated Samvev implementation."""

import argparse
import json
import os

import pytest

from scripts import provision_connection as pc

REAL_URL = os.environ.get("SAMVEV_REAL_URL", "")
pytestmark = [
    pytest.mark.skipif(not REAL_URL, reason="Requires isolated Samvev fixture"),
    pytest.mark.enable_socket,
]


def test_actual_manager_provisions_and_reuses_static_sharing(
    tmp_path, monkeypatch, capsys, socket_enabled
):
    """Actual server confirms six grants and a no-op retry keeps the identity."""
    if REAL_URL != "http://127.0.0.1:4193":
        pytest.fail("Refusing any URL except the isolated localhost fixture")
    monkeypatch.setattr(
        pc.getpass, "getpass", lambda _prompt: "Synthetic-HA-roundtrip-password-42"
    )
    output = tmp_path / "synthetic-connection.json"
    args = argparse.Namespace(
        url=REAL_URL,
        email="ha-owner@example.invalid",
        household=None,
        name="Synthetic actual provisioning proof",
        inspect=False,
        share_groceries=True,
        share_household=True,
        person=[],
        calendar_source=[],
        all_current_persons=True,
        all_current_calendar_sources=True,
        allow_shared_native_writes=True,
        reuse_existing=True,
        messages=True,
        calendar=True,
        write_groceries=True,
        write_messages=True,
        write_calendar=True,
        output=output,
    )
    first_session = pc.ManagerSession(REAL_URL)
    try:
        pc.provision(args, first_session)
    finally:
        first_session.close()
    original = output.read_bytes()
    inode = output.stat().st_ino
    secret = json.loads(original)
    second_session = pc.ManagerSession(REAL_URL)
    try:
        before = second_session.bearer_connection(secret["api_token"])
        pc.provision(args, second_session)
        after = second_session.bearer_connection(secret["api_token"])
        assert before == after
        assert output.read_bytes() == original
        assert output.stat().st_ino == inode
        assert len(after["capabilities"]) == 6
        assert after["grants"]["listIds"] == ["groceries"]
        assert after["grants"]["household"] is True
        assert after["grants"]["allowSharedNativeWrites"] is True
        assert len(after["grants"]["personIds"]) == 2
        assert len(after["grants"]["calendarSourceIds"]) == 1
        assert capsys.readouterr().out.splitlines() == [str(output), str(output)]
    finally:
        base = f"/api/v1/households/{secret['household_id']}/integrations"
        connections = second_session.request("GET", base)["connections"]
        current = next(
            row for row in connections if row["id"] == secret["connection_id"]
        )
        second_session.request(
            "POST",
            f"{base}/{current['id']}/revoke",
            {"expectedRevision": current["revision"]},
        )
        second_session.close()
