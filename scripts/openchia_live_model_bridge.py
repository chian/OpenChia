"""Opt-in local model bridge for the live Episode acceptance test.

Run from the repository: python scripts/openchia_live_model_bridge.py --socket PATH
The test runner remains credential-free. Only this host process uses the user's
normally configured model transport. The private Unix socket accepts the same
closed model request schema as the isolated Run broker; it exposes no other
tools. This host-only acceptance harness has no admitted Episode tree and is
not a Run broker or a per-Episode launch router.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from episode_runtime.broker import admit_model_request, admit_model_response, model_response_record
from llm_call_library.transport import call_model_transport


async def serve(path, request_timeout):
    parent = path.parent.stat()
    if (
        path.parent.is_symlink()
        or not stat.S_ISDIR(parent.st_mode)
        or (hasattr(os, "getuid") and parent.st_uid != os.getuid())
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise ValueError(
            "socket parent must be an owned private directory with mode 0700"
        )
    count = 0

    async def handle(reader, writer):
        nonlocal count
        try:
            request = json.loads(await reader.readline())
            if request.get("timeout") is None:
                request["timeout"] = request_timeout
            count += 1
            print(f"Live model call {count}: {request['task']}", flush=True)
            response = await call_model_transport(admit_model_request(request))
            payload = {"response": model_response_record(admit_model_response(model_response_record(response)))}
            print(f"Completed call {count}: {dict(response.route)}", flush=True)
        except Exception as exc:
            payload = {"error": type(exc).__name__}
            print(
                f"Live transport failed: {type(exc).__name__}; cause={type(exc.__cause__).__name__}",
                flush=True,
            )
        writer.write(json.dumps(payload).encode() + b"\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    if path.exists():
        raise ValueError("socket path already exists; use a fresh private directory")
    server = await asyncio.start_unix_server(
        handle, path=str(path), limit=4 * 1024 * 1024
    )
    os.chmod(path, 0o600)
    print(f"Ready: {path}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--request-timeout", type=float, default=180)
    args = parser.parse_args()
    try:
        asyncio.run(serve(args.socket, args.request_timeout))
    except KeyboardInterrupt:
        pass
