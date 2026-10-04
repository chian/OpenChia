"""Create a private, explicit launch selection without changing a chat session.

The output is the existing /launch format, not another routing registry. Keys
are prompted without echo and written to a separate private dotenv file; public
settings and command output contain references only. Setup never calls a model.
"""

import getpass
from pathlib import Path
import re
import sys

from agent.episode_launch import read_launch_spec, resolve_launch, validate_launch_spec
from utils import atomic_json_write, atomic_write_text


def _choose(question, choices):
    from .curses_ui import curses_single_select

    selected = curses_single_select(question, choices)
    if selected is None:
        raise ValueError("launch setup cancelled; no configuration was written")
    return choices[selected]


def interactive_spec():
    if not sys.stdin.isatty():
        raise ValueError(
            "interactive setup needs a terminal; use --from for structured input"
        )
    project = input("Project name: ").strip()
    root = Path(input("Project directory: ").strip()).expanduser().resolve(strict=True)
    routes = {}
    while True:
        name = input("Model route name (blank when finished): ").strip()
        if not name:
            break
        if name in routes:
            raise ValueError("route names must be unique")
        provider = input(f"{name}: provider identifier: ").strip()
        model = input(f"{name}: exact served model name: ").strip()
        base_url = input(f"{name}: service base URL: ").strip()
        mode = _choose(
            f"{name}: service API",
            ["chat_completions", "codex_responses", "anthropic_messages"],
        )
        authentication = _choose(f"{name}: authentication", ["API key / token", "None"])
        auth = {"kind": "none"}
        if authentication != "None":
            env = input(
                f"{name}: credential variable name (reference, not the key): "
            ).strip()
            auth = {
                "kind": "env",
                "env": env,
                "account": input(f"{name}: account label: ").strip(),
            }
        routes[name] = {
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "api_mode": mode,
            "auth": auth,
            "fallbacks": [],
        }
    if not routes:
        raise ValueError("at least one model route is required")
    slots = {}
    while True:
        slot = input("Function model slot name (blank when finished): ").strip()
        if not slot:
            break
        if slot in slots:
            raise ValueError("model slot names must be unique")
        slots[slot] = _choose(f"{slot}: use which model route?", list(routes))
    if not slots:
        raise ValueError("at least one function model slot is required")
    builder = {
        "planning": _choose("Builder planning uses which model slot?", list(slots)),
        "emission": _choose("Builder code emission uses which model slot?", list(slots)),
    }
    return validate_launch_spec({
        "project": project,
        "project_root": str(root),
        "env_files": [],
        "routes": routes,
        "model_slots": slots,
        "builder_slots": builder,
    })


def credential_names(spec):
    return sorted({
        route["auth"]["env"]
        for route in spec["routes"].values()
        if route["auth"]["kind"] == "env"
    })


def save_setup(directory, spec, credentials):
    """Save only to a new operator-selected directory; never overwrite a setup."""
    from .config import _quote_env_value

    spec = validate_launch_spec(spec)
    spec.pop("source_file", None)
    spec["project_root"] = str(
        Path(spec["project_root"]).expanduser().resolve(strict=True)
    )
    names = credential_names(spec)
    if set(credentials) - set(names):
        raise ValueError("credential input names a key not referenced by this launch")
    for name, value in credentials.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(
                "credential variable name must be a valid environment identifier"
            )
        if (
            not isinstance(value, str)
            or not value
            or any(c in value for c in "\x00\r\n")
        ):
            raise ValueError("credential must be nonempty, single-line text")
    directory = Path(directory).expanduser().absolute()
    # A newly created 0700 directory protects both files while publishing them.
    # Refuse an existing path (including symlinks); never chmod or overwrite it.
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    if credentials:
        secret_file = directory / "credentials.env"
        atomic_write_text(
            secret_file,
            "".join(
                f"{name}={_quote_env_value(credentials[name])}\n"
                for name in sorted(credentials)
            ),
            mode=0o600,
            fsync_dir=True,
        )
        spec["env_files"].append(str(secret_file))
    configuration = directory / "launch.json"
    # Resolve using the exact ordinary /launch path. Neither the process env nor
    # a profile's ambient credentials are modified or borrowed by setup.
    # Resolve before publishing the public file: the resolver also rejects a
    # credential accidentally copied into a public model or endpoint field.
    resolved = resolve_launch({**spec, "source_file": str(configuration)})
    atomic_json_write(configuration, spec, mode=0o600, fsync_dir=True)
    return {
        "launch_file": str(configuration),
        "configuration_hash": resolved.configuration_hash,
        "model_slots": resolved.record["resolved_spec"]["model_slots"],
        "builder_slots": resolved.record["resolved_spec"]["builder_slots"],
        "credential_names": names,
        "credentials_written": sorted(credentials),
        "credentials_file": str(directory / "credentials.env") if credentials else None,
        "activated": False,
        "approved": False,
        "next": [
            f"/launch load {configuration}",
            "/launch preview",
            "/launch approve HASH_FROM_PREVIEW",
        ],
    }


def setup_launch(args):
    spec = read_launch_spec(args.source) if args.source else interactive_spec()
    credentials = {}
    if args.prompt_credentials or not args.source:
        if not sys.stdin.isatty():
            raise ValueError(
                "credential entry requires a terminal; use explicit env_files for unattended setup"
            )
        for name in credential_names(spec):
            credentials[name] = getpass.getpass(f"Value for {name} (hidden): ")
    return save_setup(args.directory, spec, credentials)
