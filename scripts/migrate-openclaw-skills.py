"""Migrate openclaw skills to innie agent skill directories.

Strips metadata.openclaw line from SKILL.md frontmatter.
Copies references/ subdir if present.

Usage:
    python scripts/migrate-openclaw-skills.py [--dry-run]
"""

import re
import shutil
import sys
from pathlib import Path

OPENCLAW_SKILLS = Path("/opt/homebrew/lib/node_modules/openclaw/skills")
INNIE_AGENTS = Path.home() / ".innie/agents"

AVERY_SKILLS = {
    "1password", "apple-notes", "apple-reminders", "bear-notes",
    "blucli", "camsnap", "eightctl", "gifgrep", "gog", "goplaces",
    "healthcheck", "notion", "obsidian", "openai-image-gen",
    "openai-whisper", "openai-whisper-api", "openhue", "ordercli",
    "peekaboo", "sherpa-onnx-tts", "songsee", "sonoscli",
    "spotify-player", "things-mac", "wacli", "weather",
}

OAK_SKILLS = {
    "blogwatcher", "canvas", "coding-agent", "discord", "gemini",
    "gh-issues", "github", "himalaya", "mcporter", "model-usage",
    "nano-banana-pro", "nano-pdf", "oracle", "sag", "session-logs",
    "slack", "summarize", "tmux", "trello", "video-frames", "xurl",
}

BOTH_SKILLS = {"skill-creator"}

DROP_SKILLS = {"bluebubbles", "clawhub", "imsg", "voice-call"}


def strip_openclaw_metadata(content: str) -> str:
    """Remove the metadata.openclaw line from YAML frontmatter."""
    return re.sub(r"^metadata:.*\n", "", content, flags=re.MULTILINE)


def migrate_skill(skill_dir: Path, agent: str, dry_run: bool) -> None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        print(f"  SKIP {skill_dir.name} — no SKILL.md")
        return

    dest_dir = INNIE_AGENTS / agent / "skills" / skill_dir.name
    print(f"  {'[DRY]' if dry_run else '     '} {skill_dir.name} → {agent}")

    if dry_run:
        return

    dest_dir.mkdir(parents=True, exist_ok=True)
    content = skill_md.read_text(encoding="utf-8")
    content = strip_openclaw_metadata(content)
    (dest_dir / "SKILL.md").write_text(content, encoding="utf-8")

    # Copy references/ subdir if present
    refs = skill_dir / "references"
    if refs.exists() and refs.is_dir():
        dest_refs = dest_dir / "references"
        if dest_refs.exists():
            shutil.rmtree(dest_refs)
        shutil.copytree(refs, dest_refs)

    # Copy any other non-SKILL.md files
    for f in skill_dir.iterdir():
        if f.name != "SKILL.md" and f.name != "references" and f.is_file():
            shutil.copy2(f, dest_dir / f.name)


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("DRY RUN — no files will be written\n")

    if not OPENCLAW_SKILLS.exists():
        print(f"ERROR: openclaw skills not found at {OPENCLAW_SKILLS}")
        sys.exit(1)

    skill_dirs = sorted(d for d in OPENCLAW_SKILLS.iterdir() if d.is_dir())
    total = len(skill_dirs)
    migrated = 0
    dropped = 0
    unknown = []

    for skill_dir in skill_dirs:
        name = skill_dir.name
        if name in DROP_SKILLS:
            print(f"  DROP  {name}")
            dropped += 1
            continue
        targets = list(BOTH_SKILLS & {name}) and ["avery", "oak"]
        if not targets:
            if name in AVERY_SKILLS:
                targets = ["avery"]
            elif name in OAK_SKILLS:
                targets = ["oak"]
            elif name in BOTH_SKILLS:
                targets = ["avery", "oak"]
            else:
                unknown.append(name)
                print(f"  ???   {name} — not in triage table, skipping")
                continue

        for agent in targets:
            migrate_skill(skill_dir, agent, dry_run)
        migrated += 1

    print(f"\n{'DRY RUN ' if dry_run else ''}Results: {migrated} migrated, {dropped} dropped, {len(unknown)} unknown")
    if unknown:
        print(f"Unknown skills (add to triage table): {unknown}")


if __name__ == "__main__":
    main()
