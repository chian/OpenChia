"""OpenChia-owned Codex configuration and the standalone launch entry point.

Never derive this home from CODEX_HOME: it may belong to the Codex session
running OpenChia. Explicit homes belong to individual Implementer contexts.
"""

from pathlib import Path

from hermes_constants import get_hermes_home


DEFAULT_CODEX_CONFIG = '''# OpenChia's Codex defaults; not the user's personal Codex configuration.
default_permissions = ":workspace"
'''


def resolve_codex_home(codex_home: str | Path | None = None) -> Path:
    """One location shared by the launcher, app-server, and config migration."""
    return (Path(codex_home).expanduser() if codex_home is not None
            else get_hermes_home() / "codex").resolve()


def prepare_codex_home(codex_home: str | Path | None = None) -> Path:
    """Initialize only a missing private config; preserve existing local settings."""
    from utils import atomic_write_text

    home = resolve_codex_home(codex_home)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    config = home / "config.toml"
    if not config.exists():
        atomic_write_text(config, DEFAULT_CODEX_CONFIG, tmp_prefix=".config.toml.")
    return home


def codex_child_env(env: dict[str, str], codex_home: str | Path | None = None) -> dict[str, str]:
    """Keep parent Codex thread/permission state out of OpenChia's native child."""
    child = {key: value for key, value in env.items() if not key.startswith("CODEX_")}
    child["CODEX_HOME"] = str(prepare_codex_home(codex_home))
    return child


def main() -> None:
    """Run Codex with OpenChia's config without exporting settings to the caller."""
    import os
    import sys

    from openchia_cli.codex_runtime_switch import get_configured_codex_binary
    from openchia_cli.config import load_config_readonly
    from tools.environments.local import hermes_subprocess_env

    binary = get_configured_codex_binary(load_config_readonly())
    child_env = codex_child_env(hermes_subprocess_env())
    os.execvpe(binary, [binary, *sys.argv[1:]], child_env)
