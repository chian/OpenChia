"""Tests for /tools slash command handler in the interactive CLI."""

from unittest.mock import MagicMock, patch

from cli import OpenChiaCLIBase

def _make_cli(enabled_toolsets=None):
    """Build a minimal OpenChiaCLIBase stub without running __init__."""
    cli_obj = OpenChiaCLIBase.__new__(OpenChiaCLIBase)
    cli_obj.enabled_toolsets = set(enabled_toolsets or ["web", "memory"])
    cli_obj._command_running = False
    cli_obj.console = MagicMock()
    return cli_obj

# ── /tools (no subcommand) ──────────────────────────────────────────────────

# ── /tools list ─────────────────────────────────────────────────────────────

class TestToolsSlashList:

    def test_list_calls_backend(self, capsys):
        cli_obj = _make_cli()
        with patch("openchia_cli.tools_config.load_config",
                   return_value={"platform_toolsets": {"cli": ["web"]}}), \
             patch("openchia_cli.tools_config.save_config"):
            cli_obj._handle_tools_command("/tools list")
        out = capsys.readouterr().out
        assert "web" in out

# ── /tools disable (session reset) ──────────────────────────────────────────

class TestToolsSlashDisableWithReset:

    def test_disable_applies_directly_and_resets_session(self):
        """Disable applies immediately (no confirmation prompt) and resets session."""
        cli_obj = _make_cli(["web", "memory"])
        with patch("openchia_cli.tools_config.load_config",
                   return_value={"platform_toolsets": {"cli": ["web", "memory"]}}), \
             patch("openchia_cli.tools_config.save_config"), \
             patch("openchia_cli.tools_config._get_platform_tools", return_value={"memory"}), \
             patch("openchia_cli.config.load_config", return_value={}), \
             patch.object(cli_obj, "new_session") as mock_reset:
            cli_obj._handle_tools_command("/tools disable web")
        mock_reset.assert_called_once()
        assert "web" not in cli_obj.enabled_toolsets

# ── /tools enable (session reset) ───────────────────────────────────────────

class TestToolsSlashEnableWithReset:

    def test_enable_applies_directly_and_resets_session(self):
        """Enable applies immediately (no confirmation prompt) and resets session."""
        cli_obj = _make_cli(["memory"])
        with patch("openchia_cli.tools_config.load_config",
                   return_value={"platform_toolsets": {"cli": ["memory"]}}), \
             patch("openchia_cli.tools_config.save_config"), \
             patch("openchia_cli.tools_config._get_platform_tools", return_value={"memory", "web"}), \
             patch("openchia_cli.config.load_config", return_value={}), \
             patch.object(cli_obj, "new_session") as mock_reset:
            cli_obj._handle_tools_command("/tools enable web")
        mock_reset.assert_called_once()
        assert "web" in cli_obj.enabled_toolsets
