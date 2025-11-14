from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from linear_manager.cli import run_add


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "tester@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_run_add_creates_branch_and_worktree(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    manager_home = tmp_path / "manager"
    monkeypatch.setenv("LINEAR_MANAGER_HOME", str(manager_home))
    monkeypatch.chdir(repo)

    exit_code = run_add(
        title="Test Feature",
        description="Example description",
        team_key="ENG",
        priority=None,
        assignee=None,
        labels=None,
    )
    assert exit_code == 0

    manifest_files = list((manager_home / "tasks").glob("*.yaml"))
    assert manifest_files

    data = yaml.safe_load(manifest_files[0].read_text(encoding="utf-8"))
    branch_name = data["branch"]
    worktree_path = Path(data["worktree"])

    assert branch_name
    branch_list = subprocess.run(
        ["git", "branch", "--list", branch_name],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert branch_name in branch_list.stdout

    worktrees_root = manager_home / "worktrees"
    assert worktree_path.exists()
    assert worktree_path.is_dir()
    assert worktree_path.is_relative_to(worktrees_root)
    assert (worktree_path / ".git").exists()
    assert worktree_path.name == branch_name.replace("/", "-")


def test_run_add_handles_existing_branch(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    subprocess.run(
        ["git", "branch", "test-feature"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    manager_home = tmp_path / "manager"
    monkeypatch.setenv("LINEAR_MANAGER_HOME", str(manager_home))
    monkeypatch.chdir(repo)

    exit_code = run_add(
        title="Test Feature",
        description=None,
        team_key="ENG",
        priority=None,
        assignee=None,
        labels=None,
    )
    assert exit_code == 0

    manifest_files = list((manager_home / "tasks").glob("*.yaml"))
    assert manifest_files

    data = yaml.safe_load(manifest_files[0].read_text(encoding="utf-8"))
    branch_name = data["branch"]
    assert branch_name != "test-feature"
    assert branch_name.startswith("test-feature")

    branch_list = subprocess.run(
        ["git", "branch", "--list", branch_name],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert branch_name in branch_list.stdout
