"""Explicit refiner launch through OpenChia's existing Run executor.

Normal builds are not redirected here. The caller supplies the admitted refiner
registration, scoped brokers and the one shared validation service. This module
does not provision a worker, synthesize Run evidence, or implement replay.
Its result retains existing Run evidence and the host's exact verified-build
receipt or unresolved gaps. It does not initiate successor approval or production.
"""

import asyncio

from .runtime import RefinementSession
from .outcome import RefinementRunResult
from .finalization import finalize_result
from .handoff import attach_review


async def execute_refinement(
    *,
    store,
    campaign_id,
    registration,
    source_package_path,
    executor,
    model_broker,
    http_broker,
    evaluations,
) -> RefinementRunResult:
    session = await asyncio.to_thread(
        RefinementSession,
        store=store,
        campaign_id=campaign_id,
        registration=registration,
        source_package_path=source_package_path,
        evaluations=evaluations,
    )
    evidence = await executor.execute(
        registration=registration,
        source_package_path=source_package_path,
        model_broker=model_broker,
        http_broker=http_broker,
        refinement_session=session,
    )
    result = await asyncio.to_thread(finalize_result, session, evidence)
    return await asyncio.to_thread(attach_review, session, result)
