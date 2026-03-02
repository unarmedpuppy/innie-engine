"""Tests for heartbeat extraction schema."""

import pytest
from pydantic import ValidationError

from innie.heartbeat.schema import (
    HeartbeatExtraction,
    JournalEntry,
    Learning,
    OpenItem,
    ProcessedSessions,
)


def test_minimal_extraction():
    ext = HeartbeatExtraction(
        journal_entries=[JournalEntry(date="2026-03-02", time="10:00", summary="Built auth flow")],
        processed_sessions=ProcessedSessions(count=1, session_ids=["sess-001"]),
    )
    assert len(ext.journal_entries) == 1
    assert ext.processed_sessions.count == 1


def test_full_extraction():
    ext = HeartbeatExtraction(
        journal_entries=[
            JournalEntry(
                date="2026-03-02",
                time="10:00",
                summary="Built auth",
                details="JWT + refresh",
            )
        ],
        learnings=[
            Learning(
                category="patterns",
                title="RRF",
                content="Reciprocal Rank Fusion",
                confidence="high",
            )
        ],
        open_items=[OpenItem(action="add", text="Deploy to staging", priority="p1")],
        processed_sessions=ProcessedSessions(count=2, session_ids=["s1", "s2"]),
    )
    assert ext.learnings[0].category == "patterns"
    assert ext.open_items[0].action == "add"


def test_missing_required_fields():
    with pytest.raises(ValidationError):
        HeartbeatExtraction()


def test_learning_categories():
    for cat in ["debugging", "patterns", "tools", "infrastructure", "processes"]:
        entry = Learning(category=cat, title="Test", content="Content")
        assert entry.category == cat


def test_journal_serialization():
    ext = HeartbeatExtraction(
        journal_entries=[JournalEntry(date="2026-03-02", time="14:30", summary="Test")],
        processed_sessions=ProcessedSessions(count=1, session_ids=["x"]),
    )
    data = ext.model_dump()
    assert data["journal_entries"][0]["date"] == "2026-03-02"
