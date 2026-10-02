"""Installed ``openchia`` command for the Duet CLI host."""

from __future__ import annotations

import sys


OPENCHIA_HELP = """usage: openchia [options]

OpenChia starts an interactive human-LLM Duet that specifies and approves
nested Episode workflows. An explicit build materializes an approved design
without executing it; /run separately launches the admitted materialization.

options:
  -m, --model MODEL       model for the Duet and Episode conversations
  --provider PROVIDER     inference provider
  --resume SESSION        resume a named OpenChia conversation
  --reasoning LEVEL       reasoning effort
  --max-turns N           maximum model/tool iterations per conversation turn
  --verbose               show detailed runtime output
  -h, --help              show this help

Inside OpenChia, use /episode to browse the Workflow Architecture and its
Materialized Specification, and /help for the complete control list.
"""


def _openchia_chat_main(**kwargs):
    from cli import main as cli_main
    from openchia_cli.openchia_cli import OpenChiaCLI

    return cli_main(cli_class=OpenChiaCLI, **kwargs)


def _openchia_provider_setup(_args) -> bool:
    """Configure only the inference provider OpenChia needs, then continue."""

    print()
    print("OpenChia needs an inference provider before the Duet can start.")
    print()
    try:
        reply = input("Configure a provider now? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        reply = "n"
    if reply in {"n", "no"}:
        print("Provider setup skipped. Run openchia again when you are ready.")
        return False
    try:
        from openchia_cli.main import (
            _has_any_provider_configured,
            select_provider_and_model,
        )

        select_provider_and_model()
    except (EOFError, KeyboardInterrupt, SystemExit):
        print()
        print("Provider setup cancelled. Run openchia to try again.")
        return False
    if not _has_any_provider_configured():
        print("Provider setup did not complete. Run openchia to try again.")
        return False
    print("Provider configured. Starting the OpenChia Duet.")
    return True


def main() -> None:
    if {"-h", "--help"} & set(sys.argv[1:]):
        print(OPENCHIA_HELP)
        return
    unsupported = {"-z", "--oneshot", "--tui", "--tui-native"}
    selected = sorted(unsupported & set(sys.argv[1:]))
    if selected:
        raise SystemExit(
            "openchia is an interactive Duet session; unsupported option(s): "
            + ", ".join(selected)
        )
    # OpenChia's navigational surface is implemented in the classic
    # prompt_toolkit layout.  Force that surface even when the inherited
    # Hermes profile defaults to the separate TypeScript TUI.
    if "--cli" not in sys.argv[1:]:
        sys.argv.insert(1, "--cli")
    from openchia_cli.main import run_with_chat_cli_main

    run_with_chat_cli_main(
        _openchia_chat_main,
        first_run_setup=_openchia_provider_setup,
    )


if __name__ == "__main__":
    main()
