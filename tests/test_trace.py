"""Tests for trace logging and SQLite trace database."""

import json
import time

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


# ── SQLite trace DB tests ──────────────────────────────────────────────


def test_open_creates_db():
    conn = trace.open_trace_db()
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "trace_sessions" in tables
    assert "trace_spans" in tables
    conn.close()


def test_start_and_end_session():
    conn = trace.open_trace_db()

    sid = trace.start_session(
        conn,
        agent_name="test-agent",
        model="claude-sonnet",
        cwd="/tmp/test",
    )
    assert sid.startswith("ses-")

    trace.end_session(
        conn,
        session_id=sid,
        cost_usd=0.05,
        input_tokens=1000,
        output_tokens=500,
        num_turns=3,
    )

    session = trace.get_session(conn, sid)
    assert session is not None
    assert session.agent_name == "test-agent"
    assert session.model == "claude-sonnet"
    assert session.cost_usd == 0.05
    assert session.input_tokens == 1000
    assert session.output_tokens == 500
    assert session.num_turns == 3
    assert session.end_time is not None
    conn.close()


def test_record_span():
    conn = trace.open_trace_db()

    sid = trace.start_session(conn, agent_name="test")
    span_id = trace.record_span(
        conn,
        session_id=sid,
        tool_name="Read",
        input_json='{"file": "test.py"}',
        output_summary="File contents (200 lines)",
        start_time=time.time() - 0.5,
        end_time=time.time(),
        duration_ms=500.0,
    )
    assert span_id.startswith("spn-")

    session = trace.get_session(conn, sid)
    assert len(session.spans) == 1
    assert session.spans[0].tool_name == "Read"
    assert session.spans[0].duration_ms == 500.0
    conn.close()


def test_list_sessions():
    conn = trace.open_trace_db()

    trace.start_session(conn, agent_name="alpha")
    trace.start_session(conn, agent_name="beta")
    trace.start_session(conn, agent_name="alpha")

    all_sessions = trace.list_sessions(conn)
    assert len(all_sessions) == 3

    alpha_only = trace.list_sessions(conn, agent_name="alpha")
    assert len(alpha_only) == 2
    conn.close()


def test_get_stats():
    conn = trace.open_trace_db()

    sid1 = trace.start_session(conn, agent_name="agent1", model="sonnet")
    trace.record_span(conn, session_id=sid1, tool_name="Read")
    trace.record_span(conn, session_id=sid1, tool_name="Edit")
    trace.record_span(conn, session_id=sid1, tool_name="Read")
    trace.end_session(conn, session_id=sid1, cost_usd=0.10, input_tokens=2000, output_tokens=1000, num_turns=5)

    sid2 = trace.start_session(conn, agent_name="agent2")
    trace.record_span(conn, session_id=sid2, tool_name="Bash")
    trace.end_session(conn, session_id=sid2, cost_usd=0.03, input_tokens=500, output_tokens=200, num_turns=2)

    stats = trace.get_stats(conn)
    assert stats.total_sessions == 2
    assert stats.total_spans == 4
    assert stats.total_cost_usd == pytest.approx(0.13)
    assert stats.total_input_tokens == 2500
    assert stats.total_output_tokens == 1200
    assert stats.tool_usage["Read"] == 2
    assert stats.tool_usage["Edit"] == 1
    assert stats.tool_usage["Bash"] == 1
    assert stats.sessions_by_agent["agent1"] == 1
    assert stats.sessions_by_agent["agent2"] == 1
    conn.close()


def test_stats_filter_by_agent():
    conn = trace.open_trace_db()

    sid1 = trace.start_session(conn, agent_name="avery")
    trace.end_session(conn, session_id=sid1, cost_usd=0.05)

    sid2 = trace.start_session(conn, agent_name="gilfoyle")
    trace.end_session(conn, session_id=sid2, cost_usd=0.20)

    avery_stats = trace.get_stats(conn, agent_name="avery")
    assert avery_stats.total_sessions == 1
    assert avery_stats.total_cost_usd == pytest.approx(0.05)
    conn.close()


def test_explicit_session_id():
    conn = trace.open_trace_db()

    sid = trace.start_session(conn, session_id="my-custom-id", agent_name="test")
    assert sid == "my-custom-id"

    session = trace.get_session(conn, "my-custom-id")
    assert session is not None
    assert session.agent_name == "test"
    conn.close()
