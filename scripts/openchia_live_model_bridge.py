"""Opt-in local model bridge for the live Episode acceptance test.

Run from the repository: python scripts/openchia_live_model_bridge.py --socket PATH
The test runner remains credential-free. Only this host process uses the user's
normally configured model transport. The private Unix socket accepts the same
closed model requests as the isolated Run broker; it exposes no other tools.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from episode_runtime.broker import ScopedModelBroker, model_response_record
from llm_call_library.transport import call_model_transport


async def serve(path, request_timeout):
    broker = ScopedModelBroker(call_model_transport)
    count = 0

    async def handle(reader, writer):
        nonlocal count
        try:
            request = json.loads(await reader.readline())
            if request.get("timeout") is None:
                request["timeout"] = request_timeout
            count += 1
            print(f"Live model call {count}: {request['task']}", flush=True)
            response = await broker(request)
            payload = {"response": model_response_record(response)}
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
