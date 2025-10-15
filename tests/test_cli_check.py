from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import yaml

from linear_manager.cli import _strip_ansi, main


def _write_manifest(path: Path, content: str) -> None:
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


def test_check_tests_updates_manifest(monkeypatch, tmp_path, capsys) -> None:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    worktrees = tmp_path / "worktrees" / "feature"
    worktrees.mkdir(parents=True)

    manifest = manifests / "issue.yaml"
    _write_manifest(
        manifest,
        """
        defaults:
          team_key: ENG

        issues:
          - title: Example task
            branch: feature/example
            worktree: ../worktrees/feature
        """,
    )

    calls: list[tuple[Path, str]] = []

    def fake_run_checks(worktree: Path, branch: str) -> dict[str, object]:
        calls.append((worktree, branch))
        return {
            "pass_or_fail": "pass",
            "failure_reason": None,
            "details": [
                {
                    "name": "ci",
                    "bucket": "pass",
                    "state": "SUCCESS",
                }
            ],
            "exit_code": 0,
        }

    from linear_manager import cli as cli_module

    monkeypatch.setattr(cli_module, "_run_gh_checks", fake_run_checks)

    result = main(["check", "tests", str(manifests)])

    assert result == 0
    assert calls == [(worktrees.resolve(), "feature/example")]

    out = _strip_ansi(capsys.readouterr().out)
    assert "issue.yaml" in out
    assert "pass" in out

    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    issue = data["issues"][0]
    tests = issue["tests"]
    assert tests["pass_or_fail"] == "pass"
    assert tests.get("failure_reason") in (None, "")
    assert tests["branch"] == "feature/example"
    assert tests["worktree"].endswith("worktrees/feature")
    assert tests["details"][0]["name"] == "ci"
    assert "checked_at" in tests


def test_check_tests_marks_missing_branch(tmp_path, capsys) -> None:
    manifest = tmp_path / "task.yaml"
    _write_manifest(
        manifest,
        """
        defaults:
          team_key: ENG

        issues:
          - title: Needs branch
        """,
    )

    result = main(["check", "tests", str(manifest)])

    assert result == 0
    out = _strip_ansi(capsys.readouterr().out)
    assert "missing_branch" in out

    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    tests = data["issues"][0]["tests"]
    assert tests["pass_or_fail"] == "missing_branch"
    assert tests["failure_reason"]
    assert "checked_at" in tests
