# ADR-0021 — Obsidian Compatibility via Frontmatter and Wikilinks

- **Date:** 2026-03-02
- **Status:** Accepted
- **Repos/Services affected:** innie-engine

## Context

The knowledge base (`data/`) is plain markdown files. Many users (including us) use Obsidian as a markdown knowledge management tool. Obsidian supports YAML frontmatter for metadata and `[[wikilinks]]` for cross-referencing. We could either build Obsidian-native features or make our existing markdown compatible.

## Decision

Add YAML frontmatter and wikilinks to all routed files (heartbeat pipeline and skills). No Obsidian-specific tooling, plugins, or vault generation. Users point Obsidian at `data/` and it works.

## Options Considered

### Option A: Ignore Obsidian
Plain markdown with no frontmatter or links. Works everywhere but loses Obsidian's graph view, Dataview queries, and tag filtering.

### Option B: Obsidian plugin
Build an Obsidian plugin that integrates with innie. Heavy investment, requires maintaining a separate codebase in a different ecosystem, and ties us to Obsidian specifically.

### Option C: Frontmatter + wikilinks (selected)
Light touch: every routed file gets YAML frontmatter (`date`, `type`, `tags`, `category`, etc.) and cross-references use `[[wikilinks]]` format. This is valid markdown everywhere — non-Obsidian tools just show the frontmatter as text and wikilinks as plain text.

Frontmatter fields vary by content type:
- Journal: `date`, `type: journal`, `tags`
- Learnings: `date`, `type: learning`, `category`, `confidence`, `tags`
- Decisions: `date`, `type: decision`, `status`, `project`
- Meetings: `date`, `type: meeting`, `attendees`
- People: `date`, `type: person`, `role`, `tags`

Wikilinks format: `[[projects/slug/context|Display Name]]`, `[[people/slug|Name]]`

### Option D: Multiple vault support
Generate `.obsidian/` config directory with custom CSS, templates, graph settings. Too opinionated and would conflict with existing user Obsidian configs.

## Consequences

### Positive
- Obsidian graph view shows relationships between projects, people, and decisions
- Dataview queries work (`TABLE date, type FROM "data" WHERE type = "learning"`)
- Tag-based filtering in Obsidian sidebar
- Zero Obsidian-specific code — just markdown conventions
- Works with any markdown tool, not locked to Obsidian

### Negative / Tradeoffs
- Frontmatter adds 3-6 lines to every file
- Wikilinks are Obsidian-specific syntax — other tools show them as plain text `[[like this]]`
- No custom Obsidian themes or graph styling

### Risks
- Frontmatter schema changes would affect Dataview queries. Mitigated by keeping the schema stable and documenting it in README.
