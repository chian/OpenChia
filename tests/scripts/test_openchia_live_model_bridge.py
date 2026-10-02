"""The credential-bearing bridge is private before its socket is bound."""

import asyncio
from pathlib import Path
import stat

import pytest

from scripts import openchia_live_model_bridge as bridge


@pytest.mark.platforms("posix")
@pytest.mark.asyncio
async def test_bridge_rejects_public_parent_and_binds_inside_private_directory(
    tmp_path, monkeypatch
):
    # A relative path avoids AF_UNIX's short pathname limit under pytest's
    # nested temporary roots, while still binding inside the isolated home.
    monkeypatch.chdir(tmp_path)
    parent = Path("bridge")
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
    socket = parent / "model.sock"
    with pytest.raises(ValueError, match="private directory"):
        await bridge.serve(socket, 180)
    assert not socket.exists()

    parent.chmod(0o700)
    bound = asyncio.Event()
    servers = []
    start = asyncio.start_unix_server

    async def observe_bind(*args, **kwargs):
        assert stat.S_IMODE(parent.stat().st_mode) == 0o700
        server = await start(*args, **kwargs)
        servers.append(server)
        bound.set()
        return server

    monkeypatch.setattr(asyncio, "start_unix_server", observe_bind)
    task = asyncio.create_task(bridge.serve(socket, 180))
    try:
        await asyncio.wait_for(bound.wait(), 5)
        assert servers[0].is_serving()
        assert stat.S_IMODE(socket.stat().st_mode) == 0o600
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
