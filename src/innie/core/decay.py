"""Memory decay — automated pruning and archival of stale content.

Three decay operations:
1. Archive old CONTEXT.md items (>30 days without update)
2. Compress old session logs (>90 days → monthly summary)
3. Deindex stale content (remove from search index if source file deleted)
"""

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from innie.core import paths

logger = logging.getLogger(__name__)


def decay_context(
    agent: str | None = None,
    max_age_days: int = 30,
    dry_run: bool = False,
) -> dict:
    """Archive old items from CONTEXT.md.

    Items with dates older than max_age_days are moved to
    data/journal/ as an archived context snapshot.
    """
    ctx_file = paths.context_file(agent)
    if not ctx_file.exists():
        return {"archived": 0, "remaining": 0}

    content = ctx_file.read_text()
    lines = content.splitlines()
    cutoff = datetime.now() - timedelta(days=max_age_days)

    # Find lines that look like dated items: "- [2026-01-15] something"
    date_pattern = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})\]")

    keep = []
    archived = []

    for line in lines:
        match = date_pattern.match(line.strip())
        if match:
            try:
                item_date = datetime.strptime(match.group(1), "%Y-%m-%d")
                if item_date < cutoff:
                    archived.append(line)
                    continue
            except ValueError:
                pass
        keep.append(line)

    if archived and not dry_run:
        # Write archived items to journal
        today = datetime.now()
        archive_dir = paths.journal_dir(agent) / str(today.year) / f"{today.month:02d}"
        archive_dir.mkdir(parents=True, exist_ok=True)

        archive_file = archive_dir / f"{today.day:02d}-context-archive.md"
        with open(archive_file, "a") as f:
            f.write(f"\n## Context Archive ({today.strftime('%Y-%m-%d %H:%M')})\n\n")
            for line in archived:
                f.write(f"{line}\n")
            f.write("\n")

        # Rewrite CONTEXT.md without archived items
        ctx_file.write_text("\n".join(keep) + "\n")
        logger.info(f"Archived {len(archived)} items from CONTEXT.md")

    return {"archived": len(archived), "remaining": len(keep)}


def decay_sessions(
    agent: str | None = None,
    max_age_days: int = 90,
    dry_run: bool = False,
) -> dict:
    """Compress old session logs into monthly summaries.

    Session logs older than max_age_days are concatenated into
    a single monthly summary file and the individual files are removed.
    """
    sessions_dir = paths.sessions_dir(agent)
    if not sessions_dir.exists():
        return {"compressed": 0, "removed": 0}

    cutoff = datetime.now() - timedelta(days=max_age_days)
    date_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")

    # Group old files by month
    by_month: dict[str, list[Path]] = {}
    for session_file in sorted(sessions_dir.glob("*.md")):
        match = date_pattern.match(session_file.name)
        if not match:
            continue
        try:
            file_date = datetime.strptime(match.group(1), "%Y-%m-%d")
        except ValueError:
            continue

        if file_date < cutoff:
            month_key = file_date.strftime("%Y-%m")
            by_month.setdefault(month_key, []).append(session_file)

    compressed = 0
    removed = 0

    for month_key, files in by_month.items():
        if len(files) < 2:
            continue  # Don't compress single files

        if dry_run:
            compressed += 1
            removed += len(files)
            continue

        # Create monthly summary
        summary_file = sessions_dir / f"{month_key}-summary.md"
        with open(summary_file, "w") as out:
            out.write(f"# Session Summary — {month_key}\n\n")
            out.write(f"*Compressed from {len(files)} daily logs*\n\n")

            for session_file in files:
                content = session_file.read_text()
                # Take first ~20 lines of each as summary
                lines = content.splitlines()[:20]
                out.write(f"## {session_file.stem}\n\n")
                out.write("\n".join(lines))
                out.write("\n\n---\n\n")

        # Remove original files
        for session_file in files:
            session_file.unlink()
            removed += 1

        compressed += 1
        logger.info(f"Compressed {len(files)} sessions into {summary_file}")

    return {"compressed": compressed, "removed": removed}


def decay_index(agent: str | None = None, dry_run: bool = False) -> dict:
    """Remove stale entries from the search index.

    Checks if source files still exist; removes index entries for deleted files.
    """
    db_path = paths.index_db(agent)
    if not db_path.exists():
        return {"removed": 0}

    try:
        from innie.core.search import open_db

        conn = open_db(db_path)
        cursor = conn.execute("SELECT DISTINCT file_path FROM chunks")
        indexed_files = [row[0] for row in cursor.fetchall()]

        stale = [f for f in indexed_files if not Path(f).exists()]

        if stale and not dry_run:
            for filepath in stale:
                # Get chunk IDs for this file
                chunk_ids = [
                    r[0]
                    for r in conn.execute(
                        "SELECT id FROM chunks WHERE file_path = ?", (filepath,)
                    ).fetchall()
                ]
                if chunk_ids:
                    ph = ",".join("?" * len(chunk_ids))
                    conn.execute(f"DELETE FROM chunk_fts WHERE rowid IN ({ph})", chunk_ids)
                    try:
                        conn.execute(
                            f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({ph})",
                            chunk_ids,
                        )
                    except Exception:
                        pass
                conn.execute("DELETE FROM chunks WHERE file_path = ?", (filepath,))
                conn.execute("DELETE FROM file_index WHERE file_path = ?", (filepath,))
            conn.commit()
            logger.info(f"Removed {len(stale)} stale entries from index")

        conn.close()
        return {"removed": len(stale)}

    except Exception as e:
        logger.warning(f"Index decay failed: {e}")
        return {"removed": 0, "error": str(e)}


def decay_all(
    agent: str | None = None,
    dry_run: bool = False,
    context_max_days: int = 30,
    session_max_days: int = 90,
) -> dict:
    """Run all decay operations."""
    results = {
        "context": decay_context(agent, context_max_days, dry_run),
        "sessions": decay_sessions(agent, session_max_days, dry_run),
        "index": decay_index(agent, dry_run),
    }
    return results
