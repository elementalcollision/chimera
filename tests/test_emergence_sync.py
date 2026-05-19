"""Tests for chimera.a2a.emergence_sync (v3.8)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from chimera.a2a.emergence import record_observation
from chimera.a2a.emergence_sync import (
    _merge_into_local,
    serialize_journal,
    sync_remote_emergence,
)


@pytest.fixture
def journal(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("CHIMERA_PROTOCOL_JOURNAL_DIR", str(tmp_path))
    return tmp_path


def test_serialize_journal_emits_one_line_per_observation(journal: Path):
    record_observation("peerA", "shell", {"function": {"parameters": {"properties": {}}}}, dir=journal)
    record_observation("peerB", "kfm", {"function": {"parameters": {"properties": {"x": {}}}}}, dir=journal)
    body = serialize_journal(dir=journal)
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) == 2
    for ln in lines:
        obj = json.loads(ln)
        assert "source_peer_file" in obj
        assert obj["source_peer_file"] in ("peerA", "peerB")


def test_serialize_empty_journal_returns_empty_string(journal: Path):
    assert serialize_journal(dir=journal) == ""


def test_merge_into_local_dedupes_repeated_lines(journal: Path):
    line = json.dumps({
        "peer": "peerA", "tool": "shell", "params": [],
        "observed_at": "2026-05-18T00:00:00+00:00",
        "source_peer_file": "peerA",
    }, sort_keys=True)
    body = "\n".join([line, line])
    n1 = _merge_into_local(body, source_host="host-a", dir=journal)
    n2 = _merge_into_local(body, source_host="host-a", dir=journal)
    assert n1 == 1  # second copy in the same batch is also deduped
    assert n2 == 0
    out = journal / "remote" / "host-a" / "peerA.jsonl"
    assert out.exists()
    assert len([ln for ln in out.read_text().splitlines() if ln.strip()]) == 1


def test_sync_pulls_remote_feed_into_remote_subtree(journal: Path, monkeypatch):
    record_observation(
        "peerA", "shell",
        {"function": {"parameters": {"properties": {"cmd": {}}}}},
        dir=journal,
    )
    feed_body = serialize_journal(dir=journal)
    # Clear local journal so the sync test isn't confused with self.
    for p in journal.glob("*.jsonl"):
        p.unlink()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=feed_body)

    transport = httpx.MockTransport(handler)

    class _FakeClient(httpx.Client):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr("chimera.a2a.emergence_sync.httpx.Client", _FakeClient)

    result = sync_remote_emergence(["http://upstream:8765"])
    assert result.fetched == 1
    assert result.records_added == 1
    out_files = list((journal / "remote").rglob("*.jsonl"))
    assert len(out_files) == 1
    assert "upstream" in str(out_files[0])


def test_sync_records_failures(journal: Path, monkeypatch):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    transport = httpx.MockTransport(handler)

    class _FakeClient(httpx.Client):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr("chimera.a2a.emergence_sync.httpx.Client", _FakeClient)

    result = sync_remote_emergence(["http://locked:8765"])
    assert result.fetched == 0
    assert len(result.failures) == 1
