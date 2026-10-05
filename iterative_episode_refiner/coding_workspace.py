"""Candidate file staging and capture, not an executor or a validation harness.

Only the host's assigned paths can become a change proposal. Scratch files and
the coding agent's prose never become accepted source or measurement evidence.
"""

import json
import stat
from pathlib import Path

from .records import logical_path


PLAN_EDITS = ".openchia-plan-edits.json"
CONTEXT = ".openchia-assignment.json"


class CodingWorkspace:
    def __init__(self, root, *, source_files, writable_paths, protected_paths):
        self.root = Path(root)
        self.source_files = dict(source_files)
        self.writable_paths = set(writable_paths) - set(protected_paths)
        self.paths = set(self.source_files) | self.writable_paths
        for name in self.paths:
            logical_path(name)
            if name in {PLAN_EDITS, CONTEXT}:
                raise ValueError("assignment source overlaps coding workspace metadata")

    def _path(self, name):
        path = self.root / logical_path(name)
        # The coding agent can replace parents as well as leaf paths. Never read
        # a link (including a hard link) into host admission or overwrite through it.
        for part in (self.root, *path.relative_to(self.root).parents):
            parent = part if part == self.root else self.root / part
            if parent.is_symlink():
                raise ValueError(f"coding workspace contains a symbolic link: {name}")
        if path.is_symlink():
            raise ValueError(f"coding workspace contains a symbolic link: {name}")
        if path.exists():
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError(f"coding source must be an ordinary unlinked file: {name}")
        return path

    def stage(self, context):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name, content in self.source_files.items():
            path = self._path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        for name, value in ((CONTEXT, context), (PLAN_EDITS, {"implementation_detail_operations": []})):
            self._path(name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def capture(self):
        changes = []
        for name in sorted(self.paths):
            path = self._path(name)
            after = path.read_text(encoding="utf-8") if path.exists() else None
            before = self.source_files.get(name)
            if after == before:
                continue
            if name not in self.writable_paths:
                raise ValueError(f"coding agent changed read-only candidate source: {name}")
            changes.append({"logical_path": name, "content": after})
        plan = json.loads(self._path(PLAN_EDITS).read_text(encoding="utf-8"))
        if not isinstance(plan, dict):
            raise ValueError("plan edits must be an object")
        if set(plan) == {"prerequisite"}:
            if changes:
                raise ValueError("a prerequisite request cannot also submit file edits")
            return plan
        if set(plan) != {"implementation_detail_operations"} or not isinstance(plan["implementation_detail_operations"], list):
            raise ValueError("plan edits must contain only implementation_detail_operations")
        # Exact operation kinds, writable paths and expected candidate identity
        # are still checked by ordinary runtime_proposals._change admission.
        return {"files": changes, **plan}
