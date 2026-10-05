"""Join local host writers before a cancelled executor can publish its terminal."""

import asyncio


async def join_local(task, *, propagate_cancel):
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
    if cancelled and propagate_cancel:
        raise asyncio.CancelledError
    return result


async def commit_local(function, *args, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    return await join_local(task, propagate_cancel=True)
