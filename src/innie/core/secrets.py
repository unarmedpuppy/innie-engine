"""Secret scanning — detect API keys and tokens before indexing.

Scans file content for common secret patterns and flags them so they
are excluded from the search index.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Patterns that strongly indicate secrets
SECRET_PATTERNS = [
    # API keys (generic)
    (re.compile(r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{20,})"), "API key"),
    # AWS
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key"),
    (
        re.compile(r"(?i)aws[_-]?secret[_-]?access[_-]?key\s*[:=]\s*['\"]?([a-zA-Z0-9/+=]{40})"),
        "AWS Secret Key",
    ),
    # GitHub tokens
    (re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}"), "GitHub Token"),
    # Generic tokens/secrets
    (
        re.compile(
            r"(?i)(secret|token|password|passwd|pwd)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-!@#$%^&*]{8,})"
        ),
        "Secret/Token",
    ),
    # Bearer tokens
    (re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}"), "Bearer Token"),
    # Private keys
    (re.compile(r"-----BEGIN\s+(RSA|DSA|EC|OPENSSH)\s+PRIVATE\s+KEY-----"), "Private Key"),
    # Anthropic keys
    (re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}"), "Anthropic API Key"),
    # OpenAI keys
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "OpenAI API Key"),
    # Slack tokens
    (re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}"), "Slack Token"),
]

# Files to always skip
SKIP_EXTENSIONS = {".db", ".sqlite", ".sqlite3", ".pyc", ".pyo", ".so", ".dylib"}
SKIP_NAMES = {".env", ".env.local", ".env.production", "credentials.json", "service-account.json"}


@dataclass
class SecretFinding:
    file: str
    line_number: int
    pattern_name: str
    snippet: str  # Redacted snippet for logging


def scan_file(filepath: Path) -> list[SecretFinding]:
    """Scan a single file for secrets."""
    if filepath.suffix in SKIP_EXTENSIONS:
        return []

    if filepath.name in SKIP_NAMES:
        return [
            SecretFinding(
                file=str(filepath),
                line_number=0,
                pattern_name="Sensitive filename",
                snippet=filepath.name,
            )
        ]

    findings = []
    try:
        content = filepath.read_text(errors="ignore")
        for line_num, line in enumerate(content.splitlines(), 1):
            for pattern, name in SECRET_PATTERNS:
                if pattern.search(line):
                    # Redact the actual secret
                    snippet = line.strip()[:60] + "..." if len(line.strip()) > 60 else line.strip()
                    findings.append(
                        SecretFinding(
                            file=str(filepath),
                            line_number=line_num,
                            pattern_name=name,
                            snippet=snippet,
                        )
                    )
                    break  # One finding per line is enough
    except Exception:
        pass

    return findings


def scan_directory(directory: Path, extensions: set[str] | None = None) -> list[SecretFinding]:
    """Scan all files in a directory for secrets."""
    if not directory.exists():
        return []

    extensions = extensions or {
        ".md",
        ".yaml",
        ".yml",
        ".toml",
        ".json",
        ".txt",
        ".sh",
        ".py",
        ".js",
        ".ts",
    }
    findings = []

    for filepath in directory.rglob("*"):
        if not filepath.is_file():
            continue
        if filepath.suffix not in extensions and filepath.name not in SKIP_NAMES:
            continue
        findings.extend(scan_file(filepath))

    return findings


def should_index_file(filepath: Path) -> bool:
    """Check if a file is safe to index (no secrets detected)."""
    if filepath.name in SKIP_NAMES:
        return False
    if filepath.suffix in SKIP_EXTENSIONS:
        return False
    findings = scan_file(filepath)
    if findings:
        logger.warning(f"Skipping {filepath}: {len(findings)} potential secret(s) found")
        return False
    return True
