"""The source-controlled built-in Episode library."""

from __future__ import annotations

from .lexical_probe import DESIGN as LEXICAL_PROBE
from .page import DESIGN as PAGE
from .question_run import DESIGN as QUESTION_RUN
from .report import DESIGN as REPORT
from .registry import EpisodeLibrary
from .search_strategy import DESIGN as SEARCH_STRATEGY
from .source_table import DESIGN as SOURCE_TABLE
from .web_search import DESIGN as WEB_SEARCH


episode_library = EpisodeLibrary()
for _design in (
    QUESTION_RUN,
    SEARCH_STRATEGY,
    WEB_SEARCH,
    PAGE,
    SOURCE_TABLE,
    REPORT,
    LEXICAL_PROBE,
):
    episode_library.register(_design)
episode_library.validate_topology()


__all__ = ["episode_library"]
