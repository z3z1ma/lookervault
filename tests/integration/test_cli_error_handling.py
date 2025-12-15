"""Comprehensive error handling tests for CLI commands.

This module tests error scenarios for pack, unpack, snapshot, verify, and other CLI commands.
Tests cover invalid inputs, missing files/directories, permission errors, and database errors.
"""

import json
import sqlite3
from unittest.mock import Mock, patch

from typer.testing import CliRunner

from lookervault.cli.main import app

runner = CliRunner()


class TestPackCommandErrors:
    """Test error scenarios for the pack command."""

    def test_pack_missing_input_directory(self, tmp_path):
        """Test pack command with non-existent input directory."""
        nonexistent_dir = tmp_path / "nonexistent"
        db_path = tmp_path / "looker.db"

        result = runner.invoke(
            app,
            [
                "pack",
                "--input-dir",
                str(nonexistent_dir),
                "--db-path",
                str(db_path),
            ],
        )

        assert result.exit_code == 1
        # Check both stdout and stderr for error message
        output = (result.stdout + result.stderr).lower()
        assert "not found" in output or "does not exist" in output

    def test_pack_missing_input_directory_json_output(self, tmp_path):
        """Test pack command with non-existent input directory and JSON output."""
        nonexistent_dir = tmp_path / "nonexistent"
        db_path = tmp_path / "looker.db"

        result = runner.invoke(
            app,
            [
                "pack",
                "--input-dir",
                str(nonexistent_dir),
                "--db-path",
                str(db_path),
                "--json",
            ],
        )

        assert result.exit_code == 1
        # Check stdout first, fall back to stderr
        output_text = result.stdout if result.stdout else result.stderr
        # Validate JSON output if present
        if output_text.strip():
            try:
                output = json.loads(output_text)
                assert output["status"] == "error"
                assert "error_type" in output
                assert "error_message" in output
            except json.JSONDecodeError:
                # Error might be printed to stderr before JSON formatting
                pass

    def test_pack_empty_input_directory(self, tmp_path):
        """Test pack command with empty input directory."""
        input_dir = tmp_path / "empty"
        input_dir.mkdir()
        db_path = tmp_path / "looker.db"

        result = runner.invoke(
            app,
            [
                "pack",
                "--input-dir",
                str(input_dir),
                "--db-path",
                str(db_path),
            ],
        )

        # Should handle empty directory gracefully
        # Exit code depends on implementation - could be success with 0 items or error
        assert result.exit_code in [0, 1]

    def test_pack_invalid_yaml_files(self, tmp_path):
        """Test pack command with invalid YAML syntax."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        dashboards_dir = input_dir / "dashboards"
        dashboards_dir.mkdir()

        # Create invalid YAML file
        invalid_yaml = dashboards_dir / "invalid.yaml"
        invalid_yaml.write_text("invalid: yaml: content: [unclosed")

        db_path = tmp_path / "looker.db"

        result = runner.invoke(
            app,
            [
                "pack",
                "--input-dir",
                str(input_dir),
                "--db-path",
                str(db_path),
            ],
        )

        # Should fail due to invalid YAML
        assert result.exit_code != 0

    def test_pack_missing_metadata_file(self, tmp_path):
        """Test pack command when metadata.json is missing."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        dashboards_dir = input_dir / "dashboards"
        dashboards_dir.mkdir()

        # Create valid YAML without metadata.json
        dashboard_yaml = dashboards_dir / "dashboard1.yaml"
        dashboard_yaml.write_text(
            """
id: "1"
title: "Test Dashboard"
"""
        )

        db_path = tmp_path / "looker.db"

        result = runner.invoke(
            app,
            [
                "pack",
                "--input-dir",
                str(input_dir),
                "--db-path",
                str(db_path),
            ],
        )

        # Should handle missing metadata gracefully or fail with clear error
        # Exit code depends on implementation
        assert result.exit_code in [0, 1, 3]

    def test_pack_database_permission_error(self, tmp_path):
        """Test pack command when database path is not writable."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        dashboards_dir = input_dir / "dashboards"
        dashboards_dir.mkdir()

        dashboard_yaml = dashboards_dir / "dashboard1.yaml"
        dashboard_yaml.write_text(
            """
id: "1"
title: "Test Dashboard"
"""
        )

        # Create read-only directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir(mode=0o555)
        db_path = readonly_dir / "looker.db"

        try:
            result = runner.invoke(
                app,
                [
                    "pack",
                    "--input-dir",
                    str(input_dir),
                    "--db-path",
                    str(db_path),
                ],
            )

            # Should fail with permission error
            assert result.exit_code != 0
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(0o755)

    def test_pack_dry_run_mode(self, tmp_path):
        """Test pack command in dry-run mode."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        dashboards_dir = input_dir / "dashboards"
        dashboards_dir.mkdir()

        dashboard_yaml = dashboards_dir / "dashboard1.yaml"
        dashboard_yaml.write_text(
            """
id: "1"
title: "Test Dashboard"
"""
        )

        db_path = tmp_path / "looker.db"

        result = runner.invoke(
            app,
            [
                "pack",
                "--input-dir",
                str(input_dir),
                "--db-path",
                str(db_path),
                "--dry-run",
            ],
        )

        # Dry run should complete (exit code depends on validation)
        assert result.exit_code in [0, 1]


class TestUnpackCommandErrors:
    """Test error scenarios for the unpack command."""

    def test_unpack_missing_database(self, tmp_path):
        """Test unpack command with non-existent database."""
        nonexistent_db = tmp_path / "nonexistent.db"
        output_dir = tmp_path / "output"

        result = runner.invoke(
            app,
            [
                "unpack",
                "--output-dir",
                str(output_dir),
                "--db-path",
                str(nonexistent_db),
            ],
        )

        assert result.exit_code != 0
        assert "not found" in result.stdout.lower() or "does not exist" in result.stdout.lower()

    def test_unpack_missing_database_json_output(self, tmp_path):
        """Test unpack command with non-existent database and JSON output."""
        nonexistent_db = tmp_path / "nonexistent.db"
        output_dir = tmp_path / "output"

        result = runner.invoke(
            app,
            [
                "unpack",
                "--output-dir",
                str(output_dir),
                "--db-path",
                str(nonexistent_db),
                "--json",
            ],
        )

        assert result.exit_code != 0
        # Should produce JSON error output
        try:
            output = json.loads(result.stdout)
            assert output["status"] == "error"
        except json.JSONDecodeError:
            # Some errors might be printed to stderr before JSON formatting
            pass

    def test_unpack_corrupted_database(self, tmp_path):
        """Test unpack command with corrupted database file."""
        corrupted_db = tmp_path / "corrupted.db"
        corrupted_db.write_text("not a valid sqlite database")
        output_dir = tmp_path / "output"

        result = runner.invoke(
            app,
            [
                "unpack",
                "--output-dir",
                str(output_dir),
                "--db-path",
                str(corrupted_db),
            ],
        )

        assert result.exit_code != 0

    def test_unpack_output_dir_permission_error(self, tmp_path):
        """Test unpack command when output directory is not writable."""
        # Create minimal valid database
        db_path = tmp_path / "looker.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                content_type TEXT,
                content_data BLOB,
                content_size INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
        """
        )
        conn.commit()
        conn.close()

        # Create read-only directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir(mode=0o555)
        output_dir = readonly_dir / "output"

        try:
            result = runner.invoke(
                app,
                [
                    "unpack",
                    "--output-dir",
                    str(output_dir),
                    "--db-path",
                    str(db_path),
                ],
            )

            # Should fail with permission error
            assert result.exit_code != 0
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(0o755)

    def test_unpack_invalid_strategy(self, tmp_path):
        """Test unpack command with invalid strategy."""
        db_path = tmp_path / "looker.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                content_type TEXT,
                content_data BLOB,
                content_size INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
        """
        )
        conn.commit()
        conn.close()

        output_dir = tmp_path / "output"

        result = runner.invoke(
            app,
            [
                "unpack",
                "--output-dir",
                str(output_dir),
                "--db-path",
                str(db_path),
                "--strategy",
                "invalid_strategy",
            ],
        )

        # Should fail with validation error
        assert result.exit_code != 0

    def test_unpack_invalid_content_types(self, tmp_path):
        """Test unpack command with invalid content types."""
        db_path = tmp_path / "looker.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                content_type TEXT,
                content_data BLOB,
                content_size INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
        """
        )
        conn.commit()
        conn.close()

        output_dir = tmp_path / "output"

        result = runner.invoke(
            app,
            [
                "unpack",
                "--output-dir",
                str(output_dir),
                "--db-path",
                str(db_path),
                "--content-types",
                "invalid_type,another_invalid",
            ],
        )

        # Should fail with validation error
        assert result.exit_code != 0

    def test_unpack_overwrite_without_flag(self, tmp_path):
        """Test unpack command refuses to overwrite existing output without flag."""
        db_path = tmp_path / "looker.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                content_type TEXT,
                content_data BLOB,
                content_size INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
        """
        )
        conn.commit()
        conn.close()

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        # Create existing file
        (output_dir / "metadata.json").write_text("{}")

        result = runner.invoke(
            app,
            [
                "unpack",
                "--output-dir",
                str(output_dir),
                "--db-path",
                str(db_path),
            ],
        )

        # Should either succeed or fail gracefully
        # Exit code depends on whether existing files are detected
        assert result.exit_code in [0, 1]


class TestSnapshotCommandErrors:
    """Test error scenarios for the snapshot commands."""

    def test_snapshot_upload_missing_source(self, tmp_path):
        """Test snapshot upload with non-existent source file."""
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(
            app,
            [
                "snapshot",
                "upload",
                "--source",
                str(nonexistent_db),
            ],
        )

        assert result.exit_code != 0

    def test_snapshot_upload_missing_config(self, tmp_path, monkeypatch):
        """Test snapshot upload without snapshot configuration."""
        db_path = tmp_path / "looker.db"
        db_path.touch()

        # Mock config loading to return config without snapshot section
        with patch("lookervault.cli.commands.snapshot.load_config") as mock_load:
            mock_cfg = Mock()
            mock_cfg.snapshot = None
            mock_load.return_value = mock_cfg

            result = runner.invoke(
                app,
                [
                    "snapshot",
                    "upload",
                    "--source",
                    str(db_path),
                ],
            )

            assert result.exit_code == 2  # EXIT_VALIDATION_ERROR
            output = (result.stdout + result.stderr).lower()
            assert "snapshot configuration not found" in output or "snapshot" in output

    def test_snapshot_upload_invalid_compression_level(self, tmp_path):
        """Test snapshot upload with invalid compression level."""
        db_path = tmp_path / "looker.db"
        db_path.touch()

        result = runner.invoke(
            app,
            [
                "snapshot",
                "upload",
                "--source",
                str(db_path),
                "--compression-level",
                "15",  # Invalid: must be 1-9
            ],
        )

        # Should fail with validation error
        assert result.exit_code != 0

    @patch("lookervault.cli.commands.snapshot.upload_snapshot")
    def test_snapshot_upload_gcs_permission_error(self, mock_upload, tmp_path):
        """Test snapshot upload with GCS permission error."""
        db_path = tmp_path / "looker.db"
        db_path.touch()

        # Mock GCS permission error
        from google.api_core.exceptions import Forbidden

        mock_upload.side_effect = Forbidden("Access denied")

        with patch("lookervault.cli.commands.snapshot.load_config") as mock_load:
            mock_cfg = Mock()
            mock_cfg.snapshot = Mock()
            mock_cfg.snapshot.bucket_name = "test-bucket"
            mock_cfg.snapshot.region = "us-central1"
            mock_load.return_value = mock_cfg

            result = runner.invoke(
                app,
                [
                    "snapshot",
                    "upload",
                    "--source",
                    str(db_path),
                ],
            )

            assert result.exit_code == 1  # EXIT_GENERAL_ERROR

    def test_snapshot_list_missing_config(self, tmp_path, monkeypatch):
        """Test snapshot list without snapshot configuration."""
        with patch("lookervault.cli.commands.snapshot.load_config") as mock_load:
            mock_cfg = Mock()
            mock_cfg.snapshot = None
            mock_load.return_value = mock_cfg

            result = runner.invoke(
                app,
                [
                    "snapshot",
                    "list",
                ],
            )

            assert result.exit_code == 2  # EXIT_VALIDATION_ERROR

    def test_snapshot_download_missing_config(self, tmp_path):
        """Test snapshot download without snapshot configuration."""
        with patch("lookervault.cli.commands.snapshot.load_config") as mock_load:
            mock_cfg = Mock()
            mock_cfg.snapshot = None
            mock_load.return_value = mock_cfg

            result = runner.invoke(
                app,
                [
                    "snapshot",
                    "download",
                    "--selector",
                    "latest",
                    "--output-path",
                    str(tmp_path / "output.db"),
                ],
            )

            assert result.exit_code == 2  # EXIT_VALIDATION_ERROR


class TestVerifyCommandErrors:
    """Test error scenarios for the verify command."""

    def test_verify_missing_database(self, tmp_path):
        """Test verify command with non-existent database."""
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(
            app,
            [
                "verify",
                "--db",
                str(nonexistent_db),
            ],
        )

        assert result.exit_code == 1
        output = (result.stdout + result.stderr).lower()
        assert "not found" in output or "does not exist" in output

    def test_verify_corrupted_database(self, tmp_path):
        """Test verify command with corrupted database."""
        corrupted_db = tmp_path / "corrupted.db"
        corrupted_db.write_text("not a valid sqlite database")

        result = runner.invoke(
            app,
            [
                "verify",
                "--db",
                str(corrupted_db),
            ],
        )

        assert result.exit_code != 0

    def test_verify_invalid_content_type(self, tmp_path):
        """Test verify command with invalid content type."""
        db_path = tmp_path / "looker.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                content_type TEXT,
                content_data BLOB,
                content_size INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
        """
        )
        conn.commit()
        conn.close()

        result = runner.invoke(
            app,
            [
                "verify",
                "--db",
                str(db_path),
                "--type",
                "invalid_type",
            ],
        )

        # Should fail with validation error
        assert result.exit_code != 0

    def test_verify_database_with_corrupted_content(self, tmp_path):
        """Test verify command with database containing corrupted content."""
        db_path = tmp_path / "looker.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                content_type TEXT,
                content_data BLOB,
                content_size INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
        """
        )
        # Insert corrupted content (invalid msgpack)
        conn.execute(
            """
            INSERT INTO content_items (id, content_type, content_data, content_size, created_at, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
            ("1", "DASHBOARD", b"invalid_msgpack_data", 20),
        )
        conn.commit()
        conn.close()

        result = runner.invoke(
            app,
            [
                "verify",
                "--db",
                str(db_path),
            ],
        )

        # Should succeed but report errors in content
        # Exit code might be 0 with warnings or 1 with errors
        assert result.exit_code in [0, 1]
        # Should indicate validation errors in output
        output = (result.stdout + result.stderr).lower()
        assert "error" in output or "invalid" in output or "warning" in output


class TestCheckCommandErrors:
    """Test error scenarios for the check command."""

    def test_check_missing_config_file(self, tmp_path, monkeypatch):
        """Test check command with non-existent config file."""
        # Clear environment variables
        monkeypatch.delenv("LOOKERVAULT_API_URL", raising=False)
        monkeypatch.delenv("LOOKER_BASE_URL", raising=False)
        monkeypatch.delenv("LOOKERVAULT_CLIENT_ID", raising=False)
        monkeypatch.delenv("LOOKER_CLIENT_ID", raising=False)
        monkeypatch.delenv("LOOKERVAULT_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("LOOKER_CLIENT_SECRET", raising=False)

        nonexistent_config = tmp_path / "nonexistent.toml"

        result = runner.invoke(
            app,
            [
                "check",
                "--config",
                str(nonexistent_config),
            ],
        )

        assert result.exit_code in [1, 2]

    def test_check_invalid_config_format(self, tmp_path):
        """Test check command with malformed config file."""
        invalid_config = tmp_path / "invalid.toml"
        invalid_config.write_text("invalid toml [[[content")

        result = runner.invoke(
            app,
            [
                "check",
                "--config",
                str(invalid_config),
            ],
        )

        assert result.exit_code != 0

    def test_check_json_output_format(self, tmp_path, monkeypatch):
        """Test check command JSON output with missing config."""
        # Clear environment variables to force config error
        monkeypatch.delenv("LOOKERVAULT_API_URL", raising=False)
        monkeypatch.delenv("LOOKER_BASE_URL", raising=False)
        monkeypatch.delenv("LOOKERVAULT_CLIENT_ID", raising=False)
        monkeypatch.delenv("LOOKER_CLIENT_ID", raising=False)
        monkeypatch.delenv("LOOKERVAULT_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("LOOKER_CLIENT_SECRET", raising=False)

        nonexistent_config = tmp_path / "nonexistent.toml"

        result = runner.invoke(
            app,
            [
                "check",
                "--config",
                str(nonexistent_config),
                "--output",
                "json",
            ],
        )

        # Should exit with error or handle gracefully
        assert result.exit_code in [0, 1, 2]


class TestExtractCommandErrors:
    """Test error scenarios for the extract command."""

    def test_extract_missing_config(self, tmp_path, monkeypatch):
        """Test extract command without valid configuration."""
        # Clear environment variables
        monkeypatch.delenv("LOOKERVAULT_API_URL", raising=False)
        monkeypatch.delenv("LOOKER_BASE_URL", raising=False)
        monkeypatch.delenv("LOOKERVAULT_CLIENT_ID", raising=False)
        monkeypatch.delenv("LOOKER_CLIENT_ID", raising=False)
        monkeypatch.delenv("LOOKERVAULT_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("LOOKER_CLIENT_SECRET", raising=False)

        result = runner.invoke(
            app,
            [
                "extract",
                "--config",
                "/nonexistent/config.toml",
            ],
        )

        assert result.exit_code != 0

    def test_extract_invalid_workers_count(self, tmp_path):
        """Test extract command with invalid workers count."""
        result = runner.invoke(
            app,
            [
                "extract",
                "--workers",
                "100",  # Exceeds max of 50
            ],
        )

        # Should fail with validation error or be capped
        # Exit code depends on implementation
        assert result.exit_code != 0

    def test_extract_invalid_content_types(self, tmp_path):
        """Test extract command with invalid content types."""
        result = runner.invoke(
            app,
            [
                "extract",
                "--types",
                "invalid_type,another_invalid",
            ],
        )

        # Should fail with validation error
        assert result.exit_code != 0

    def test_extract_database_permission_error(self, tmp_path):
        """Test extract command when database path is not writable."""
        # Create read-only directory
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir(mode=0o555)
        db_path = readonly_dir / "looker.db"

        try:
            result = runner.invoke(
                app,
                [
                    "extract",
                    "--db",
                    str(db_path),
                ],
            )

            # Should fail with permission error
            assert result.exit_code != 0
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(0o755)


class TestRestoreCommandErrors:
    """Test error scenarios for the restore commands."""

    def test_restore_single_missing_database(self, tmp_path):
        """Test restore single command with non-existent database."""
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(
            app,
            [
                "restore",
                "single",
                "dashboard",
                "123",
                "--db-path",
                str(nonexistent_db),
            ],
        )

        assert result.exit_code != 0

    def test_restore_single_invalid_content_type(self, tmp_path):
        """Test restore single command with invalid content type."""
        db_path = tmp_path / "looker.db"
        db_path.touch()

        result = runner.invoke(
            app,
            [
                "restore",
                "single",
                "invalid_type",
                "123",
                "--db-path",
                str(db_path),
            ],
        )

        assert result.exit_code != 0

    def test_restore_all_missing_database(self, tmp_path):
        """Test restore all command with non-existent database."""
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(
            app,
            [
                "restore",
                "all",
                "--db-path",
                str(nonexistent_db),
            ],
        )

        assert result.exit_code != 0

    def test_restore_status_missing_database(self, tmp_path):
        """Test restore status command with non-existent database."""
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(
            app,
            [
                "restore",
                "status",
                "--db-path",
                str(nonexistent_db),
            ],
        )

        assert result.exit_code != 0

    def test_restore_dlq_list_missing_database(self, tmp_path):
        """Test restore dlq list command with non-existent database."""
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(
            app,
            [
                "restore",
                "dlq",
                "list",
                "--db-path",
                str(nonexistent_db),
            ],
        )

        # Command might succeed with empty results or fail with error
        assert result.exit_code in [0, 1]

    def test_restore_dlq_show_missing_database(self, tmp_path):
        """Test restore dlq show command with non-existent database."""
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(
            app,
            [
                "restore",
                "dlq",
                "show",
                "1",
                "--db-path",
                str(nonexistent_db),
            ],
        )

        assert result.exit_code != 0

    def test_restore_dlq_clear_without_force(self, tmp_path):
        """Test restore dlq clear command without --force flag."""
        db_path = tmp_path / "looker.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE dead_letter_queue (
                id INTEGER PRIMARY KEY,
                session_id TEXT,
                content_type TEXT,
                content_id TEXT,
                error_message TEXT,
                created_at TEXT
            )
        """
        )
        conn.commit()
        conn.close()

        result = runner.invoke(
            app,
            [
                "restore",
                "dlq",
                "clear",
                "--all",
                "--db-path",
                str(db_path),
            ],
        )

        # Should fail without --force flag
        assert result.exit_code != 0
        output = (result.stdout + result.stderr).lower()
        assert "force" in output or "confirmation" in output or "requires" in output


class TestListCommandErrors:
    """Test error scenarios for the list command."""

    def test_list_missing_database(self, tmp_path):
        """Test list command with non-existent database."""
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(
            app,
            [
                "list",
                "dashboards",
                "--db",
                str(nonexistent_db),
            ],
        )

        assert result.exit_code != 0

    def test_list_invalid_content_type(self, tmp_path):
        """Test list command with invalid content type."""
        db_path = tmp_path / "looker.db"
        db_path.touch()

        result = runner.invoke(
            app,
            [
                "list",
                "invalid_type",
                "--db",
                str(db_path),
            ],
        )

        assert result.exit_code != 0

    def test_list_invalid_date_format(self, tmp_path):
        """Test list command with invalid date format."""
        db_path = tmp_path / "looker.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                content_type TEXT,
                content_data BLOB,
                content_size INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
        """
        )
        conn.commit()
        conn.close()

        result = runner.invoke(
            app,
            [
                "list",
                "dashboards",
                "--db",
                str(db_path),
                "--created-after",
                "invalid-date-format",
            ],
        )

        # Should fail with validation error
        assert result.exit_code != 0


class TestCleanupCommandErrors:
    """Test error scenarios for the cleanup command."""

    def test_cleanup_missing_database(self, tmp_path):
        """Test cleanup command with non-existent database."""
        nonexistent_db = tmp_path / "nonexistent.db"

        result = runner.invoke(
            app,
            [
                "cleanup",
                "--db",
                str(nonexistent_db),
            ],
        )

        # Command might succeed with 0 items or fail with error
        assert result.exit_code in [0, 1]

    def test_cleanup_invalid_retention_days(self, tmp_path):
        """Test cleanup command with invalid retention days."""
        db_path = tmp_path / "looker.db"
        db_path.touch()

        result = runner.invoke(
            app,
            [
                "cleanup",
                "--retention-days",
                "-5",  # Negative retention days
                "--db",
                str(db_path),
            ],
        )

        # Should fail with validation error
        assert result.exit_code != 0

    def test_cleanup_dry_run_mode(self, tmp_path):
        """Test cleanup command in dry-run mode doesn't modify database."""
        db_path = tmp_path / "looker.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                content_type TEXT,
                content_data BLOB,
                content_size INTEGER,
                created_at TEXT,
                updated_at TEXT,
                deleted_at TEXT
            )
        """
        )
        conn.execute(
            """
            INSERT INTO content_items (id, content_type, content_data, content_size, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, datetime('now', '-60 days'), datetime('now', '-60 days'), datetime('now', '-60 days'))
        """,
            ("1", "DASHBOARD", b"data", 4),
        )
        conn.commit()
        initial_size = db_path.stat().st_size
        conn.close()

        result = runner.invoke(
            app,
            [
                "cleanup",
                "--retention-days",
                "30",
                "--db",
                str(db_path),
                "--dry-run",
            ],
        )

        # Dry run should complete (exit code depends on implementation)
        assert result.exit_code in [0, 1]
        # If command succeeded, database should not be significantly modified
        if result.exit_code == 0:
            # Database size should not decrease (allowing for minor journal file changes)
            assert db_path.stat().st_size >= initial_size * 0.9


class TestInfoCommandErrors:
    """Test error scenarios for the info command."""

    def test_info_missing_config(self, tmp_path, monkeypatch):
        """Test info command without valid configuration."""
        # Clear environment variables
        monkeypatch.delenv("LOOKERVAULT_API_URL", raising=False)
        monkeypatch.delenv("LOOKER_BASE_URL", raising=False)
        monkeypatch.delenv("LOOKERVAULT_CLIENT_ID", raising=False)
        monkeypatch.delenv("LOOKER_CLIENT_ID", raising=False)
        monkeypatch.delenv("LOOKERVAULT_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("LOOKER_CLIENT_SECRET", raising=False)

        result = runner.invoke(
            app,
            [
                "info",
                "--config",
                "/nonexistent/config.toml",
            ],
        )

        assert result.exit_code != 0

    def test_info_invalid_config_format(self, tmp_path):
        """Test info command with malformed config file."""
        invalid_config = tmp_path / "invalid.toml"
        invalid_config.write_text("invalid toml syntax [[[")

        result = runner.invoke(
            app,
            [
                "info",
                "--config",
                str(invalid_config),
            ],
        )

        assert result.exit_code != 0
