"""Small constructors for immutable source-backed Episode components."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from function_library import LibraryFunction, SourceSymbolReference


REFERENCE_REPOSITORY = "https://github.com/chian/nano-graphrag"
REFERENCE_REVISION = "546526a77bd34ca79ea16f16549640d22fa86851"


def source_symbol(path: str, symbol: str) -> SourceSymbolReference:
    return SourceSymbolReference(
        repository=REFERENCE_REPOSITORY,
        revision=REFERENCE_REVISION,
        path=path,
        symbol=symbol,
    )


def source_function(
    *,
    function_id: str,
    interface: str,
    description: str,
    input_type: str,
    output_type: str,
    sources: Sequence[tuple[str, str]],
    effect: str,
    failure_contract: str,
    provenance: Mapping[str, object] | None = None,
) -> LibraryFunction:
    """Define a pinned reference without claiming it can execute locally."""

    return LibraryFunction(
        library="question_pipeline",
        function_id=function_id,
        interface=interface,
        description=description,
        implementation=None,
        source_symbols=tuple(source_symbol(path, symbol) for path, symbol in sources),
        input_type=input_type,
        output_type=output_type,
        effect=effect,
        failure_contract=failure_contract,
        provenance={
            "reference_kind": "source_pinned_episode_component",
            **dict(provenance or {}),
        },
    )


__all__ = [
    "REFERENCE_REPOSITORY",
    "REFERENCE_REVISION",
    "source_function",
    "source_symbol",
]
