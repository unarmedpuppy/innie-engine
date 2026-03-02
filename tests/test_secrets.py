"""Tests for secret scanning."""

from innie.core.secrets import scan_file, should_index_file


def test_detects_openai_key(tmp_path):
    f = tmp_path / "config.md"
    f.write_text('OPENAI_API_KEY="sk-proj-1234567890abcdef1234567890abcdef"\n')
    findings = scan_file(f)
    assert len(findings) >= 1


def test_detects_aws_key(tmp_path):
    f = tmp_path / "creds.md"
    f.write_text("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n")
    findings = scan_file(f)
    assert len(findings) >= 1


def test_detects_github_token(tmp_path):
    f = tmp_path / "tokens.md"
    f.write_text("token: ghp_1234567890abcdef1234567890abcdef12\n")
    findings = scan_file(f)
    assert len(findings) >= 1


def test_clean_file_passes(tmp_path):
    f = tmp_path / "clean.md"
    f.write_text("# Meeting Notes\n\nDiscussed the new API design.\n")
    findings = scan_file(f)
    assert len(findings) == 0


def test_should_index_skips_env(tmp_path):
    f = tmp_path / ".env"
    f.write_text("SECRET=abc123\n")
    assert should_index_file(f) is False


def test_should_index_skips_binary_ext(tmp_path):
    f = tmp_path / "data.db"
    f.write_text("binary stuff")
    assert should_index_file(f) is False


def test_should_index_allows_clean_md(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("# Notes\nJust some plain notes.\n")
    assert should_index_file(f) is True
