"""Real file/SQLite recovery failures, crash replay and secret boundaries."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
from threading import Barrier
import uuid

import pytest

from server.audit_journal import AuditJournal, MAX_EVENT_BYTES
from server.config import ServerSettings
from server.store import ServerStore, isoformat, utc_now


def make_store(path: Path) -> ServerStore:
    store = ServerStore(
        ServerSettings(
            data_dir=path,
            database_path=path / "server.sqlite3",
            credential_path=path / "credential.json",
        )
    )
    store.initialize()
    return store


def event(event_id=None):
    return {
        "id": event_id or str(uuid.uuid4()),
        "occurred_at": isoformat(utc_now()),
        "actor_type": "api_key",
        "actor_id": "mk_prefix",
        "action": "device.property.set",
        "source_ip": "127.0.0.1",
        "request_path": "/api/v1/devices/lamp/property",
        "request_id": "request-1",
        "result": "success",
        "duration_ms": 12,
        "metadata": {"device": "lamp", "siid": 2, "piid": 1},
    }


def block_audit_inserts(store):
    with store._database.connect() as conn:
        conn.execute("""CREATE TRIGGER block_audit BEFORE INSERT ON audit_log
                        BEGIN SELECT RAISE(ABORT, 'test storage failure'); END""")


def unblock_audit_inserts(store):
    with store._database.connect() as conn:
        conn.execute("DROP TRIGGER block_audit")


def test_real_sqlite_failure_is_durable_and_recovered_once_on_restart(tmp_path):
    store = make_store(tmp_path)
    block_audit_inserts(store)
    receipt = store.add_audit("device.property.set", "success", metadata={"device": "lamp"})
    assert receipt["delivery"] == "queued"
    queued = tmp_path / "audit-pending" / f"{receipt['id']}.json"
    assert queued.is_file()
    pending = store.get_audit_event(receipt["id"])
    assert pending["delivery"] == "queued" and pending["metadata"] == {"device": "lamp"}
    assert store.flush_pending_audit()["pending"] == 1
    assert queued.exists()
    unblock_audit_inserts(store)
    restarted = make_store(tmp_path)
    stored = restarted.get_audit_event(receipt["id"])
    assert stored["delivery"] == "stored" and "metadata_json" not in stored
    assert restarted.audit_status() == {"pending": 0, "invalid": 0, "unavailable": 0}
    assert len(restarted.list_audit()) == 1
    assert restarted.flush_pending_audit()["delivered"] == 0


def test_receipt_can_be_read_from_pending_while_database_is_unreadable(tmp_path):
    store = make_store(tmp_path)
    block_audit_inserts(store)
    receipt = store.add_audit("device.property.set", "unknown", metadata={"device": "lamp"})
    broken = tmp_path / "broken.sqlite3"
    broken.write_text("this is not a sqlite database", encoding="utf-8")
    store.settings.database_path = broken
    result = store.get_audit_event(receipt["id"])
    assert result["delivery"] == "queued" and result["result"] == "unknown"
    assert store.flush_pending_audit()["pending"] == 1


def test_crash_after_database_commit_before_queue_unlink_is_idempotent(tmp_path):
    store = make_store(tmp_path)
    queued = event()
    store._audit_journal.save(queued)

    def commit_then_crash(record):
        store._persist_audit_event(record)
        raise SystemExit("simulated process crash after commit")

    with pytest.raises(SystemExit):
        store._audit_journal.replay(commit_then_crash)
    assert store.audit_status()["pending"] == 1
    assert len(store.list_audit()) == 1
    restarted = make_store(tmp_path)
    assert len(restarted.list_audit()) == 1
    assert restarted.get_audit_event(queued["id"])["delivery"] == "stored"
    assert restarted.audit_status()["pending"] == 0


def test_two_store_replayers_cannot_create_duplicate_audit_rows(tmp_path):
    first, second = make_store(tmp_path), make_store(tmp_path)
    records = [event() for _ in range(4)]
    for record in records:
        first._audit_journal.save(record)
    read_same_first_file = Barrier(2)

    def replay(store):
        first_call = True

        def persist(record):
            nonlocal first_call
            if first_call:
                first_call = False
                read_same_first_file.wait(timeout=5)
            store._persist_audit_event(record)

        return store._audit_journal.replay(persist)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(replay, [first, second]))
    assert all(result["unavailable"] == 0 for result in results)
    assert {row["id"] for row in first.list_audit()} == {record["id"] for record in records}
    assert first.audit_status()["pending"] == 0


@pytest.mark.parametrize(
    "fault", ["missing-field", "metadata-list", "wrong-id", "duration", "bad-time", "secret"]
)
def test_bad_schema_is_quarantined_without_blocking_later_valid_event(tmp_path, fault):
    store = make_store(tmp_path)
    bad = event("00000000-0000-0000-0000-000000000001")
    if fault == "missing-field":
        bad.pop("action")
    elif fault == "metadata-list":
        bad["metadata"] = []
    elif fault == "wrong-id":
        bad["id"] = str(uuid.uuid4())
    elif fault == "duration":
        bad["duration_ms"] = -1
    elif fault == "bad-time":
        bad["occurred_at"] = "not a date"
    else:
        bad["metadata"] = {"password": "do-not-replay-this-secret"}
    good = event()
    store._audit_journal.save(good)
    path = store._audit_journal.path / "00000000-0000-0000-0000-000000000001.json"
    path.write_text(json.dumps({"version": 1, "event": bad}), encoding="utf-8")
    result = store._audit_journal.replay(store._persist_audit_event, limit=1)
    assert result["delivered"] == 1 and result["invalid"] == 1 and result["pending"] == 0
    assert [row["id"] for row in store.list_audit()] == [good["id"]]


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"[]",
        b"\xff",
        b'{"version":1,"version":1,"event":{}}',
        b"x" * (MAX_EVENT_BYTES + 1),
        b"[" * 2000 + b"0" + b"]" * 2000,
    ],
    ids=["truncated", "array", "encoding", "duplicate-fields", "oversized", "deep-json"],
)
def test_invalid_json_and_oversized_files_are_isolated(tmp_path, raw):
    journal = AuditJournal(tmp_path)
    good = event()
    journal.save(good)
    bad_path = journal.path / f"{uuid.uuid4()}.json"
    bad_path.write_bytes(raw)
    assert journal.get(bad_path.stem) is None
    assert journal.status()["invalid"] == 1
    assert journal.get(good["id"]) == good


def create_symlink(link: Path, target: Path, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("Host cannot create symlinks")


def test_file_symlink_is_never_read_or_overwritten_and_does_not_block_valid_replay(tmp_path):
    store = make_store(tmp_path)
    good = event()
    store._audit_journal.save(good)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside private content", encoding="utf-8")
    bad_id = "00000000-0000-0000-0000-000000000001"
    link = store._audit_journal.path / f"{bad_id}.json"
    create_symlink(link, outside)
    with pytest.raises(OSError):
        store._audit_journal.save(event(bad_id))
    result = store.flush_pending_audit()
    assert result["delivered"] == 1 and result["invalid"] == 1
    assert outside.read_text(encoding="utf-8") == "outside private content"
    assert len(store.list_audit()) == 1


@pytest.mark.parametrize("link_location", ["directory", "parent"])
def test_queue_and_parent_symlinks_are_rejected_without_touching_target(tmp_path, link_location):
    target = tmp_path / "target"
    target.mkdir()
    if link_location == "parent":
        alias = tmp_path / "alias"
        create_symlink(alias, target, directory=True)
        journal = AuditJournal(alias)
    else:
        create_symlink(tmp_path / "audit-pending", target, directory=True)
        journal = AuditJournal(tmp_path)
    with pytest.raises(OSError):
        journal.save(event())
    assert journal.replay(lambda _: pytest.fail("unsafe queue must never replay"))["delivered"] == 0
    assert journal.status()["invalid"] == 1
    assert list(target.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX private file and directory modes")
def test_recovery_file_is_fsynced_private_and_queue_is_private(tmp_path, monkeypatch):
    journal = AuditJournal(tmp_path)
    fsynced_modes = []
    original = os.fsync

    def tracked_fsync(descriptor):
        fsynced_modes.append(os.fstat(descriptor).st_mode)
        original(descriptor)

    monkeypatch.setattr(os, "fsync", tracked_fsync)
    record = event()
    journal.save(record)
    assert any(stat.S_ISREG(mode) for mode in fsynced_modes)
    assert any(stat.S_ISDIR(mode) for mode in fsynced_modes)
    assert stat.S_IMODE((journal.path / f"{record['id']}.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(journal.path.stat().st_mode) == 0o700


def test_interrupted_atomic_publish_preserves_old_complete_event(tmp_path, monkeypatch):
    journal = AuditJournal(tmp_path)
    record = event()
    journal.save(record)
    changed = deepcopy(record)
    changed["metadata"]["device"] = "other lamp"

    def interrupted_replace(*args, **kwargs):
        raise OSError("simulated publication failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "replace", interrupted_replace)
        with pytest.raises(OSError):
            journal.save(changed)
    assert journal.get(record["id"]) == record
    assert not list(journal.path.glob(".pending-*"))


def test_metadata_secrets_are_redacted_but_receipt_identity_and_device_names_survive(tmp_path):
    store = make_store(tmp_path)
    key_id = str(uuid.uuid4())
    metadata = {
        "api_key_id": key_id,
        "key_id": key_id,
        "username": "camera-user",
        "device": "客厅灯",
        "password": "private-password",
        "secret_token": "private-token",
        "nested": {"Authorization": "Bearer private-bearer", "message": "token=private-query"},
    }
    stored = store.add_audit("test", "success", metadata=metadata, request_id="locate-this-request")
    block_audit_inserts(store)
    queued = store.add_audit("test", "success", metadata=metadata, request_id="locate-this-request")
    text = (store._audit_journal.path / f"{queued['id']}.json").read_text(encoding="utf-8")
    assert all(
        secret not in text
        for secret in ("private-password", "private-token", "private-bearer", "private-query")
    )
    for record in (store.get_audit_event(stored["id"]), store.get_audit_event(queued["id"])):
        assert record["metadata"]["api_key_id"] == key_id
        assert record["metadata"]["key_id"] == key_id
        assert record["metadata"]["username"] == "camera-user"
        assert record["metadata"]["device"] == "客厅灯"
        assert record["request_id"] == "locate-this-request"


def test_sqlite_and_filesystem_failure_do_not_raise_and_loss_count_is_threadsafe(tmp_path):
    store = make_store(tmp_path)
    block_audit_inserts(store)
    blocked = tmp_path / "blocked-journal"
    blocked.write_text("a regular file is not a recovery directory", encoding="utf-8")
    store._audit_journal.path = blocked
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda _: store.add_audit("device.property.set", "success"), range(64))
        )
    assert all(
        record["delivery"] == "unavailable" and record["result"] == "success" for record in results
    )
    assert store.audit_status()["unavailable"] == 64
    assert store.audit_status()["invalid"] == 1
    assert store.flush_pending_audit()["delivered"] == 0


def test_unreadable_entry_does_not_block_other_events_and_status_io_failure_is_reported(
    tmp_path, monkeypatch
):
    store = make_store(tmp_path)
    first = event("00000000-0000-0000-0000-000000000001")
    second = event()
    store._audit_journal.save(first)
    store._audit_journal.save(second)
    original = store._audit_journal._read_event

    def unavailable_first(path):
        if path.stem == first["id"]:
            raise PermissionError("simulated ACL read failure")
        return original(path)

    with monkeypatch.context() as scoped:
        scoped.setattr(store._audit_journal, "_read_event", unavailable_first)
        result = store.flush_pending_audit()
    assert result["delivered"] == 1 and result["pending"] == 1
    assert store.get_audit_event(second["id"])["delivery"] == "stored"
    assert store.get_audit_event(first["id"])["delivery"] == "queued"

    def unavailable_scan(*args, **kwargs):
        raise OSError("simulated scandir failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "scandir", unavailable_scan)
        assert store.audit_status()["invalid"] == 1
        assert store.flush_pending_audit()["delivered"] == 0
    assert store.audit_status()["pending"] == 1


def test_invalid_envelopes_and_schema_versions_are_quarantined(tmp_path):
    journal = AuditJournal(tmp_path)
    good = event()
    journal.save(good)
    for version in (True, 2, "1"):
        wrong = event()
        path = journal.path / f"{wrong['id']}.json"
        path.write_text(json.dumps({"version": version, "event": wrong}), encoding="utf-8")
    received = []
    result = journal.replay(received.append)
    assert result["delivered"] == 1 and result["invalid"] == 3
    assert received == [good]
