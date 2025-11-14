from __future__ import annotations


import yaml

from linear_manager.cli import run_add


def test_run_add_creates_yaml_file(tmp_path, monkeypatch):
    manager_home = tmp_path / "manager"
    monkeypatch.setenv("LINEAR_MANAGER_HOME", str(manager_home))

    exit_code = run_add(
        title="Test Feature",
        description="Example description",
        team_key="ENG",
        priority=2,
        assignee="test@example.com",
        labels=["bug", "feature"],
    )
    assert exit_code == 0

    manifest_files = list((manager_home / "tasks").glob("*.yaml"))
    assert len(manifest_files) == 1

    data = yaml.safe_load(manifest_files[0].read_text(encoding="utf-8"))
    assert data["title"] == "Test Feature"
    assert data["description"] == "Example description"
    assert data["team_key"] == "ENG"
    assert data["priority"] == 2
    assert data["assignee_email"] == "test@example.com"
    assert data["labels"] == ["bug", "feature"]


def test_run_add_creates_minimal_yaml(tmp_path, monkeypatch):
    manager_home = tmp_path / "manager"
    monkeypatch.setenv("LINEAR_MANAGER_HOME", str(manager_home))

    exit_code = run_add(
        title="Simple Task",
        description=None,
        team_key="PROD",
        priority=None,
        assignee=None,
        labels=None,
    )
    assert exit_code == 0

    manifest_files = list((manager_home / "tasks").glob("*.yaml"))
    assert len(manifest_files) == 1

    data = yaml.safe_load(manifest_files[0].read_text(encoding="utf-8"))
    assert data["title"] == "Simple Task"
    assert data["description"] == ""
    assert data["team_key"] == "PROD"
    assert "priority" not in data
    assert "assignee_email" not in data
    assert "labels" not in data
