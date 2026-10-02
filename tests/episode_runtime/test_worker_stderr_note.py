"""The host keeps a bounded tail of the worker's stderr and attaches it to the
host-side failure as an exception note, never to the evidence chain."""

from __future__ import annotations

import asyncio

from episode_runtime import executor


def _reader(payload: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(payload)
    reader.feed_eof()
    return reader


def test_drain_keeps_only_the_tail() -> None:
    async def run() -> bytes:
        return await executor._drain_stderr(_reader(b"x" * 10_000 + b"END"))

    tail = asyncio.run(run())
    assert len(tail) == executor.WORKER_STDERR_TAIL_BYTES
    assert tail.endswith(b"END")


def test_note_is_attached_to_the_failure_only_when_present() -> None:
    async def run(payload: bytes) -> BaseException:
        exc = RuntimeError("worker protocol stream ended inside a frame")
        task = asyncio.create_task(executor._drain_stderr(_reader(payload)))
        await executor._attach_worker_stderr(exc, task)
        return exc

    noisy = asyncio.run(run(b"isolated worker failed: ImportError: cannot import name 'X'\n"))
    assert noisy.__notes__ == [
        "worker stderr: isolated worker failed: ImportError: cannot import name 'X'"
    ]
    quiet = asyncio.run(run(b""))
    assert not getattr(quiet, "__notes__", [])
