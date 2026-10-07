"""Environment preparation through the same systemd/container Run backends.

The caller admits the recipe and constructs the package-manager command. This
module supplies only the backend's isolated process and complete diagnostics;
it neither selects dependencies nor grants an Episode runtime network access.
"""

import asyncio
import json
import os
from pathlib import Path
import secrets


# Native launchers may add their own environment. Strip it before invoking PM,
# retaining only the caller's explicit preparation settings and credentials.
_EXEC = (
    "import json,os,sys; names=json.loads(sys.argv[1]); "
    "env={name:os.environ[name] for name in names}; "
    "os.execvpe(sys.argv[2],sys.argv[2:],env)"
)


def _path(value):
    path = Path(value)
    if not path.is_absolute() or any(character in str(path) for character in "\x00\n\r: \t"):
        raise ValueError("preparation mount paths must be absolute and contain no whitespace or colon")
    return str(path)


def _inputs(command, read_only_paths, writable_directory, environment, network_access):
    if not isinstance(command, tuple) or not command or any(
        not isinstance(argument, str) or "\x00" in argument for argument in command
    ):
        raise ValueError("preparation requires an explicit command tuple")
    if not Path(command[0]).is_absolute():
        raise ValueError("preparation executable must be an absolute backend path")
    if not isinstance(network_access, bool):
        raise TypeError("preparation network access must be explicit")
    directory = Path(writable_directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("preparation output must be an existing managed directory")
    directory = directory.resolve(strict=True)
    if directory == Path(directory.anchor):
        raise ValueError("filesystem root cannot be a preparation output")
    writable = _path(directory)
    mounts = tuple((_path(Path(source).resolve(strict=True)), _path(target)) for source, target in read_only_paths)
    for source, target in mounts:
        if Path(writable).is_relative_to(Path(target)) or Path(target).is_relative_to(Path(writable)):
            raise ValueError("read-only preparation input overlaps writable output")
        if Path(source).is_relative_to(directory) or directory.is_relative_to(Path(source)):
            raise ValueError("preparation source overlaps writable output")
    if len({target for _, target in mounts}) != len(mounts):
        raise ValueError("preparation mount targets must be unique")
    env = dict(environment)
    for key, value in env.items():
        if not isinstance(key, str) or not key or "=" in key or "\x00" in key:
            raise ValueError("preparation environment has an invalid name")
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("preparation environment values must be strings without NUL")
    return mounts, writable, env


async def _communicate(arguments, *, environment, stop, backend):
    process = await asyncio.create_subprocess_exec(
        *arguments, env=environment, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    output = asyncio.create_task(process.communicate())
    try:
        stdout, stderr = await asyncio.shield(output)
    except BaseException:
        await stop()
        if process.returncode is None:
            process.terminate()
        await output
        raise
    return {
        "returncode": process.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "backend": backend,
    }


async def systemd_preparation(executor, command, *, read_only_paths, writable_directory, environment, network_access):
    from .executor import _systemd_properties

    mounts, writable, env = _inputs(command, read_only_paths, writable_directory, environment, network_access)
    runtime = executor.python_runtime_root
    if runtime is not None and not any(Path(runtime).is_relative_to(Path(target)) for _, target in mounts):
        mounts += ((_path(runtime), _path(runtime)),)
    name = f"openchia-environment-{secrets.token_hex(16)}.service"
    overrides = {"BindReadOnlyPaths", "PrivateNetwork", "RestrictAddressFamilies", "ProtectHome"}
    properties = [value for value in _systemd_properties(executor.resources, ()) if value.partition("=")[0] not in overrides]
    properties.extend((
        # Empty read-only homes permit explicit subdirectory binds; yes makes
        # the home parents inaccessible even for an admitted interpreter.
        "ProtectHome=tmpfs",
        "BindReadOnlyPaths=" + " ".join(f"{source}:{target}" for source, target in mounts),
        f"BindPaths={writable}:{writable}", f"ReadWritePaths={writable}",
        f"PrivateNetwork={'no' if network_access else 'yes'}",
        "RestrictAddressFamilies=" + ("AF_UNIX AF_INET AF_INET6" if network_access else "AF_UNIX"),
    ))
    arguments = [
        str(executor.systemd_run), "--user", "--quiet", "--collect", "--wait", "--pipe",
        "--service-type=exec", "--expand-environment=no", f"--unit={name}",
        f"--working-directory={writable}",
        *(f"--property={value}" for value in properties),
        *(f"--setenv={key}" for key in sorted(env)),
        str(executor.python_executable), "-I", "-S", "-c", _EXEC,
        json.dumps(sorted(env)), *command,
    ]

    async def stop():
        stopped = await asyncio.create_subprocess_exec(
            str(executor.systemctl), "--user", "stop", name,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await stopped.wait()

    return await _communicate(arguments, environment={**os.environ, **env}, stop=stop, backend="systemd")


async def container_preparation(executor, command, *, read_only_paths, writable_directory, environment, network_access):
    from .container_executor import container_resource_arguments

    mounts, writable, env = _inputs(command, read_only_paths, writable_directory, environment, network_access)
    owner = Path(writable).stat()
    name = f"openchia-environment-{secrets.token_hex(16)}"
    arguments = [
        str(executor.runtime.cli), "run", "--rm", "--name", name,
        "--network", "bridge" if network_access else "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        # no-tmp: ok — tmpfs mount target inside the Linux container's own mount namespace, never host scratch
        "--user", f"{owner.st_uid}:{owner.st_gid}", "--tmpfs", "/tmp:rw,nosuid,nodev",
        "--workdir", writable, *container_resource_arguments(executor.resources),
    ]
    for source, target in mounts:
        arguments.extend(("--volume", f"{source}:{target}:ro"))
    arguments.extend(("--volume", f"{writable}:{writable}:rw"))
    for key in sorted(env):
        arguments.extend(("--env", key))
    arguments.extend((
        executor.runtime.image_id, str(executor.python_executable), "-I", "-S", "-c", _EXEC,
        json.dumps(sorted(env)), *command,
    ))

    async def stop():
        stopped = await asyncio.create_subprocess_exec(
            str(executor.runtime.cli), "rm", "--force", name,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await stopped.wait()

    return await _communicate(arguments, environment={**os.environ, **env}, stop=stop, backend="container")
