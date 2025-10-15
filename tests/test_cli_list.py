"""Tests for the `manager list` CLI command."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from linear_manager.cli import main, _strip_ansi


def _write_manifest(path: Path, content: str) -> None:
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


def test_list_outputs_table_for_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "issues.yaml"
    _write_manifest(
        manifest,
        """
        defaults:
          team_key: ENG

        issues:
          - title: Refactor login flow
            description: Improve login sequence for oauth integrations
            branch: feature/login-flow
            worktree: ../worktrees/login-flow
            status: In Progress
        """,
    )

    result = main(["list", str(manifest)])

    assert result == 0
    out = capsys.readouterr().out
    # Remove ANSI color codes for easier testing
    clean_out = _strip_ansi(out)
    assert "Title" in clean_out
    assert "Refactor login flow" in clean_out
    # Check for worktree path (may be wrapped)
    assert "worktrees/login" in clean_out
    # Check for branch (should be present by default)
    assert "feature/login-flow" in clean_out
    # Description should NOT be present without --verbose
    assert "Improve login" not in clean_out
    assert "In Progress" in clean_out


def test_list_uses_defaults_and_marks_complete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    _write_manifest(
        manifest_dir / "one.yaml",
        """
        defaults:
          team_key: ENG
          branch: feature/common
          worktree: ../worktrees/common

        issues:
          - title: Common refactor
            description: Update shared helpers
            complete: true
        """,
    )
    _write_manifest(
        manifest_dir / "two.yaml",
        """
        defaults:
          team_key: ENG

        issues:
          - title: API polish
            description: Improve API messaging
            state: Review
        """,
    )

    result = main(["list", str(manifest_dir)])

    assert result == 0
    out = capsys.readouterr().out
    # Remove ANSI color codes for easier testing
    clean_out = _strip_ansi(out)
    assert "Common refactor" in clean_out
    # Check for worktree path (may be wrapped)
    assert "worktrees/common" in clean_out
    # Check for branch (should be present by default)
    assert "feature/common" in clean_out
    # Description should NOT be present without --verbose
    assert "Update shared helpers" not in clean_out
    assert "Improve API messaging" not in clean_out
    # complete flag should surface in status column
    assert "☑" in clean_out
    assert "Review" in clean_out


def test_list_verbose_shows_descriptions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "issues.yaml"
    _write_manifest(
        manifest,
        """
        defaults:
          team_key: ENG

        issues:
          - title: Refactor login flow
            description: Improve login sequence for oauth integrations
            branch: feature/login-flow
            worktree: ../worktrees/login-flow
            status: In Progress
        """,
    )

    result = main(["list", str(manifest), "--verbose"])

    assert result == 0
    out = capsys.readouterr().out
    # Remove ANSI color codes for easier testing
    clean_out = "".join(char for char in out if char.isprintable() or char in "\n\r")
    assert "Title" in clean_out
    assert "Refactor login flow" in clean_out
    # Check for worktree path (may be wrapped)
    assert "worktrees/login" in clean_out
    # Check for branch and description (should both be present with --verbose)
    assert "feature/login-flow" in clean_out
    assert "Improve login" in clean_out
    assert "In Progress" in clean_out


def test_list_errors_for_missing_path() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["list", "does-not-exist.yaml"])
    assert excinfo.value.code == 2
