"""Pydantic models for the heartbeat extraction JSON schema."""

from pydantic import BaseModel


class JournalEntry(BaseModel):
    date: str
    time: str
    summary: str
    details: str = ""


class Learning(BaseModel):
    category: str  # debugging, patterns, tools, infrastructure, processes
    title: str
    content: str
    confidence: str = "medium"  # high, medium, low


class ProjectUpdate(BaseModel):
    project: str
    summary: str
    status: str = "active"  # active, paused, completed


class Decision(BaseModel):
    project: str
    title: str
    context: str
    decision: str
    alternatives: list[str] = []


class OpenItem(BaseModel):
    action: str  # add, complete, remove
    text: str
    priority: str = "medium"


class ContextUpdate(BaseModel):
    focus: str = ""
    priorities: list[str] = []


class ProcessedSessions(BaseModel):
    count: int
    ids: list[str] = []


class SupersededLearning(BaseModel):
    file_path: str  # relative to data/ e.g. "learnings/infrastructure/2026-02-10-foo.md"
    reason: str     # one sentence: what changed and why this is now wrong/outdated


class PersonUpdate(BaseModel):
    name: str    # lowercase: josh | abby | oliver | eloise
    content: str # markdown to append — new preferences, facts, context, events


class AgentMessage(BaseModel):
    to: str      # target agent name: gilfoyle | ralph | colin | jobin | avery
    subject: str # one-line subject
    content: str # markdown body — what the other agent needs to know


class HeartbeatExtraction(BaseModel):
    journal_entries: list[JournalEntry]
    learnings: list[Learning] = []
    project_updates: list[ProjectUpdate] = []
    decisions: list[Decision] = []
    open_items: list[OpenItem] = []
    context_updates: ContextUpdate | None = None
    superseded_learnings: list[SupersededLearning] = []
    people_updates: list[PersonUpdate] = []
    agent_messages: list[AgentMessage] = []
    processed_sessions: ProcessedSessions
