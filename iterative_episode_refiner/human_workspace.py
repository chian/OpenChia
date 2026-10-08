"""Editable Target Workflow architecture, implementation choices, and source.

This is a working copy, not a Run or an approval. Stable Episode local IDs keep
source files addressable when a design change gives the generated module a new
content-derived name. The ordinary Builder reconstructs declarations at handoff.
"""

from dataclasses import dataclass
import difflib
import json
from pathlib import Path
import stat

from agent.duet_contracts import canonical_json
from agent.episode_blueprints import workflow_blueprint_from_spec, workflow_spec_from_blueprint
from episode_builder.declaration import build_module_declaration
from episode_builder.emitter import _attach_host_declaration
from episode_runtime.target_environment import ENVIRONMENT_RECIPE_PATH

from .plan_repair import choices
from .records import logical_path


ARCHITECTURE = "architecture.json"
MATERIALIZATION = "materialization.json"
INTENT = "change_intent.md"
CONTEXT = ".openchia-context.json"


def source_path(local_id):
    return logical_path(f"episodes/{local_id}.py")


@dataclass(frozen=True)
class WorkflowEditSnapshot:
    architecture: dict
    materialization: dict
    sources: dict[str, str]
    environment: str | None
    intent: str = ""

    def as_record(self):
        return {
            "architecture": self.architecture,
            "materialization": self.materialization,
            "sources": self.sources,
            "environment": self.environment,
            "intent": self.intent,
        }

    @classmethod
    def from_record(cls, value):
        if set(value) != {"architecture", "materialization", "sources", "environment", "intent"}:
            raise ValueError("workflow editing snapshot has unexpected fields")
        return cls(**value)

    def files(self):
        result = {
            ARCHITECTURE: json.dumps(self.architecture, ensure_ascii=False, indent=2) + "\n",
            MATERIALIZATION: json.dumps(self.materialization, ensure_ascii=False, indent=2) + "\n",
            INTENT: self.intent,
            **{source_path(key): value for key, value in self.sources.items()},
        }
        if self.environment is not None:
            result[ENVIRONMENT_RECIPE_PATH] = self.environment
        return result

    def validate(self):
        """Validate editable shape; source defects remain work for refinement."""
        workflow = workflow_spec_from_blueprint(self.architecture)
        ids = {node.local_id for node in workflow.episodes}
        if not isinstance(self.materialization, dict) or set(self.materialization) != ids:
            raise ValueError("materialization.json must contain each Architecture Episode ID; use null for an unplanned Episode")
        if not isinstance(self.sources, dict) or set(self.sources) - ids:
            raise ValueError("source files must name Episodes in architecture.json")
        if any(not isinstance(value, str) for value in self.sources.values()):
            raise ValueError("Episode source must be text")
        if any(value is not None and not isinstance(value, dict) for value in self.materialization.values()):
            raise ValueError("each materialization entry must be implementation choices or null")
        if self.environment is not None and not isinstance(self.environment, str):
            raise ValueError("environment recipe must be text")
        if not isinstance(self.intent, str):
            raise ValueError("change intent must be text")
        return workflow

    def diff(self, previous):
        before, after = previous.files(), self.files()
        return "\n".join(
            "".join(difflib.unified_diff(
                before.get(path, "").splitlines(keepends=True),
                after.get(path, "").splitlines(keepends=True),
                fromfile=f"before/{path}", tofile=f"after/{path}",
            ))
            for path in sorted(before.keys() | after.keys())
            if before.get(path) != after.get(path)
        )


def snapshot_from_candidate(inputs, plan, *, files, handoff):
    """Remove only the exact existing host suffix; keep rejected raw source."""
    from .materialization_edits import source_paths

    workflow = inputs.build_request.frozen_workflow.workflow
    paths = source_paths(workflow, plan)
    original = {node.local_id: node for node in inputs.plan.nodes}
    sources = {}
    for design in workflow.episodes:
        local_id = design.local_id
        source = files.get(paths[local_id])
        if source is None:
            continue
        provenance = handoff["candidate"]["sources_by_episode"].get(local_id, {})
        if provenance.get("kind") == "emitted_module":
            edges = tuple(edge for edge in inputs.plan.all_edges if edge.parent_local_id == local_id)
            suffix = _attach_host_declaration("", build_module_declaration(
                design.contract, original[local_id], edges,
            ))
            if not source.endswith(suffix):
                raise ValueError(f"{local_id}: candidate changed its host-owned declaration")
            source = source[:-len(suffix)]
        sources[local_id] = source
    return WorkflowEditSnapshot(
        architecture=workflow_blueprint_from_spec(workflow),
        materialization={node.local_id: (
            choices(plan, node.local_id, workflow.repeatable_calls)
            if any(item.local_id == node.local_id for item in plan.nodes)
            else handoff.get("submitted_materialization", {}).get(node.local_id)
        )
                         for node in workflow.episodes},
        sources=sources,
        environment=files.get(ENVIRONMENT_RECIPE_PATH),
    )


class HumanWorkflowWorkspace:
    def __init__(self, root, baseline, context):
        self.root = Path(root)
        self.baseline = baseline
        self.context = context

    def path(self, name):
        path = self.root / logical_path(name)
        for parent in (self.root, *(self.root / part for part in path.relative_to(self.root).parents)):
            if parent.is_symlink():
                raise ValueError(f"workflow workspace contains a symbolic link: {name}")
        if path.is_symlink():
            raise ValueError(f"workflow workspace contains a symbolic link: {name}")
        if path.exists():
            value = path.stat()
            if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
                raise ValueError(f"workflow file must be an ordinary unlinked file: {name}")
        return path

    def stage(self):
        # Reopening a conversation must retain its unfinished edits.
        if self.root.exists():
            raise ValueError("workflow editing workspace already exists; reopen its conversation")
        self.root.mkdir(parents=True, mode=0o700)
        for name, text in self.baseline.files().items():
            path = self.path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.path(CONTEXT).write_text(json.dumps(self.context, ensure_ascii=False, indent=2), encoding="utf-8")

    def capture(self):
        if canonical_json(json.loads(self.path(CONTEXT).read_text(encoding="utf-8-sig"))) != canonical_json(self.context):
            raise ValueError("host context was edited; restore .openchia-context.json before handoff")
        architecture = json.loads(self.path(ARCHITECTURE).read_text(encoding="utf-8-sig"))
        workflow = workflow_spec_from_blueprint(architecture)
        sources = {}
        expected = {source_path(node.local_id): node.local_id for node in workflow.episodes}
        directory = self.root / "episodes"
        if directory.is_symlink():
            raise ValueError("workflow source directory cannot be a symbolic link")
        for path in directory.rglob("*.py"):
            name = path.relative_to(self.root).as_posix()
            if name not in expected:
                raise ValueError(f"source {name} has no Architecture Episode; update the design or remove the obsolete source")
            sources[expected[name]] = self.path(name).read_text(encoding="utf-8-sig")
        environment = self.path(ENVIRONMENT_RECIPE_PATH)
        result = WorkflowEditSnapshot(
            architecture=architecture,
            materialization=json.loads(self.path(MATERIALIZATION).read_text(encoding="utf-8-sig")),
            sources=sources,
            environment=environment.read_text(encoding="utf-8-sig") if environment.exists() else None,
            intent=self.path(INTENT).read_text(encoding="utf-8-sig"),
        )
        result.validate()
        return result
