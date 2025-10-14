"""Tests for the `manager list` CLI command."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from linear_manager.cli import main


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
    assert "Title" in out
    assert "Refactor login flow" in out
    assert "../worktrees/login-flow" in out
    assert "feature/login-flow - Improve login sequence for oauth integrations" in out
    assert "In Progress" in out


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
    assert "Common refactor" in out
    assert "../worktrees/common" in out
    assert "feature/common - Update shared helpers" in out
    # complete flag should surface in status column
    assert "complete" in out
    assert "Review" in out


def test_list_errors_for_missing_path() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["list", "does-not-exist.yaml"])
    assert excinfo.value.code == 2
