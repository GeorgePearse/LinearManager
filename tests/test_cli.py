"""Tests for CLI functionality."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from linear_manager.cli import build_parser, main


class TestCliParser:
    """Test CLI argument parsing."""

    def test_parser_sync_subcommand_single_file(self) -> None:
        """Test parsing sync subcommand with single file."""
        parser = build_parser()
        args = parser.parse_args(["sync", "issues.yaml"])
        assert args.command == "sync"
        assert args.path == Path("issues.yaml")
        assert args.dry_run is False
        assert args.mark_done is False

    def test_parser_sync_subcommand_with_flags(self) -> None:
        """Test parsing sync subcommand with flags."""
        parser = build_parser()
        args = parser.parse_args(["sync", "issues.yaml", "--dry-run", "--mark-done"])
        assert args.command == "sync"
        assert args.dry_run is True
        assert args.mark_done is True

    def test_parser_sync_subcommand_directory(self) -> None:
        """Test parsing sync subcommand with directory."""
        parser = build_parser()
        args = parser.parse_args(["sync", "manifests/"])
        assert args.command == "sync"
        assert args.path == Path("manifests/")



class TestCliMain:
    """Test main CLI entry point."""

    @patch("linear_manager.cli.run_sync")
    def test_main_sync_single_file(self, mock_run_sync: Mock) -> None:
        """Test main with sync subcommand and single file."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            f.write(b"defaults:\n  team_key: ENG\nissues:\n  - title: Test\n")
            f.flush()
            path = Path(f.name)

        try:
            result = main(["sync", str(path)])
            assert result == 0
            assert mock_run_sync.called
        finally:
            path.unlink()

    @patch("linear_manager.cli.run_sync")
    def test_main_sync_directory(self, mock_run_sync: Mock) -> None:
        """Test main with sync subcommand and directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple YAML files
            yaml1 = Path(tmpdir) / "issue1.yaml"
            yaml1.write_text("defaults:\n  team_key: ENG\nissues:\n  - title: Test1\n")
            yaml2 = Path(tmpdir) / "issue2.yaml"
            yaml2.write_text("defaults:\n  team_key: ENG\nissues:\n  - title: Test2\n")

            result = main(["sync", tmpdir])
            assert result == 0
            assert mock_run_sync.call_count == 2

    def test_main_sync_directory_no_yaml_files(self) -> None:
        """Test main with directory containing no YAML files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a non-YAML file
            (Path(tmpdir) / "test.txt").write_text("not yaml")
            with pytest.raises(SystemExit) as exc_info:
                main(["sync", tmpdir])
            assert exc_info.value.code == 2

    @patch("linear_manager.cli.run_sync")
    def test_main_sync_directory_with_failure(self, mock_run_sync: Mock) -> None:
        """Test main with directory when some files fail."""
        mock_run_sync.side_effect = [None, RuntimeError("Test error")]

        with tempfile.TemporaryDirectory() as tmpdir:
            yaml1 = Path(tmpdir) / "issue1.yaml"
            yaml1.write_text("defaults:\n  team_key: ENG\nissues:\n  - title: Test1\n")
            yaml2 = Path(tmpdir) / "issue2.yaml"
            yaml2.write_text("defaults:\n  team_key: ENG\nissues:\n  - title: Test2\n")

            result = main(["sync", tmpdir])
            assert result == 1
            assert mock_run_sync.call_count == 2


    def test_main_no_arguments(self) -> None:
        """Test main with no arguments."""
        result = main([])
        assert result == 1

    @patch("linear_manager.cli.run_sync")
    def test_main_with_dry_run(self, mock_run_sync: Mock) -> None:
        """Test main with dry-run flag."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            f.write(b"defaults:\n  team_key: ENG\nissues:\n  - title: Test\n")
            f.flush()
            path = Path(f.name)

        try:
            result = main(["sync", str(path), "--dry-run"])
            assert result == 0
            call_args = mock_run_sync.call_args[0][0]
            assert call_args.dry_run is True
        finally:
            path.unlink()

    @patch("linear_manager.cli.run_sync")
    def test_main_with_mark_done(self, mock_run_sync: Mock) -> None:
        """Test main with mark-done flag."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            f.write(b"defaults:\n  team_key: ENG\nissues:\n  - title: Test\n")
            f.flush()
            path = Path(f.name)

        try:
            result = main(["sync", str(path), "--mark-done"])
            assert result == 0
            call_args = mock_run_sync.call_args[0][0]
            assert call_args.mark_done is True
        finally:
            path.unlink()
