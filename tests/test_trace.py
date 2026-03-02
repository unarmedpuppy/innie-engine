"""Tests for trace logging."""

import json

import pytest

from innie.core import paths, trace


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("INNIE_HOME", str(tmp_path / ".innie"))
    paths.trace_dir().mkdir(parents=True, exist_ok=True)


def test_append_trace():
    trace.append_trace({"tool": "Read", "file": "test.py"})
    # Find the trace file
    trace_files = list(paths.trace_dir().glob("*.jsonl"))
    assert len(trace_files) == 1

    lines = trace_files[0].read_text().strip().split("\n")
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["tool"] == "Read"
    assert "timestamp" in event


def test_append_multiple():
    trace.append_trace({"event": "start"})
    trace.append_trace({"event": "end"})

    trace_files = list(paths.trace_dir().glob("*.jsonl"))
    lines = trace_files[0].read_text().strip().split("\n")
    assert len(lines) == 2
