"""Every intra-package import of a staged runtime module must itself be staged.

The worker runs from the staged closure alone (a closed import finder); a module
that imports a sibling the manifest omits dies at import time inside the
sandbox, after identity verification has passed.  ``episode_runtime/interpreter.py``
was such a sibling once.
"""
from __future__ import annotations

import re
from pathlib import Path

from episode_runtime.identity import _SELECTED_LOCAL_SOURCES

REPO = Path(__file__).resolve().parents[2]
_RELATIVE_IMPORT = re.compile(r"^from \.([A-Za-z_][A-Za-z0-9_]*) import", re.M)


def test_relative_imports_of_staged_episode_runtime_modules_are_staged():
    staged = {Path(item).name[:-3] for item in _SELECTED_LOCAL_SOURCES if item.startswith("episode_runtime/")}
    missing = {}
    for item in _SELECTED_LOCAL_SOURCES:
        if not item.startswith("episode_runtime/"):
            continue
        for sibling in _RELATIVE_IMPORT.findall((REPO / item).read_text(encoding="utf-8")):
            if sibling not in staged:
                missing.setdefault(item, set()).add(sibling)
    assert not missing, f"staged modules import unstaged siblings: {missing}"
