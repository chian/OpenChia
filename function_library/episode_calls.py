"""Build only the child supplied by the runtime's approved slot binding."""

from __future__ import annotations

import inspect

from .models import FunctionImplementation, LibraryFunction


async def build_repeatable_child(builder, key, request, goal_view, collaborators):
    # Invocation admission belongs to the supplied runtime builder, not emitted code.
    child = builder(key, request, goal_view, collaborators)
    if inspect.isawaitable(child):
        child = await child
    return child


BUILD_REPEATABLE_CHILD = LibraryFunction(
    library="function_library.episode_calls",
    function_id="build_repeatable_child",
    interface="episode.child_builder",
    description="Invoke an exact runtime-provided repeatable child slot.",
    implementation=FunctionImplementation(
        module="function_library.episode_calls",
        symbol="build_repeatable_child",
        is_async=True,
    ),
    input_type="runtime child builder, key, EpisodeRequest, scoped goal view, collaborators",
    output_type="Episode",
    effect="Runs the approved slot's invocation admission before constructing its child.",
    failure_contract="Propagates admission failure; never substitutes a different child.",
    provenance={
        "owner": "method_loop",
        "parameter_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
)
