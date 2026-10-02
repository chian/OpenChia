"""Concrete view models for the OpenChia Episode Workspace.

The architecture view projects the persisted Duet workflow and is the only
editable surface.  The materialized view projects one exact Builder artifact
chain and is immutable.  Both produce the same target-bearing tree entries so
the workspace can attach human notes to an exact displayed part.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping, Optional

from agent.episode_contracts import OpaqueId, Sha256Digest
from iterative_episode_refiner.contracts import (
    DuetWorkspaceNote,
    RefinementTarget,
    RefinementTargetLayer,
)


ARCHITECTURE_SURFACE = "workflow_architecture"
MATERIALIZED_SURFACE = "materialized_specification"
DEFAULT_MISSING_VALUE = "<OPENCHIA: value required>"


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError(f"{name} must be text without NUL bytes")
    if not allow_empty and not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _optional_text(value: object, name: str) -> Optional[str]:
    if value is None:
        return None
    return _text(value, name)


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _json_copy(value: object) -> Any:
    return json.loads(_canonical(value))


@dataclass(frozen=True)
class WorkspaceTarget:
    """UI wrapper over the exact persisted ``RefinementTarget`` record."""

    target_id: str
    content_hash: str
    layer: str
    artifact_id: str
    artifact_hash: str
    json_pointer: str
    episode_local_id: Optional[str]

    def __post_init__(self) -> None:
        try:
            layer = RefinementTargetLayer(self.layer)
        except (TypeError, ValueError) as exc:
            raise ValueError("workspace target layer is invalid") from exc
        target = RefinementTarget(
            layer=layer,
            artifact_id=OpaqueId(self.artifact_id),
            artifact_hash=Sha256Digest(self.artifact_hash),
            json_pointer=self.json_pointer,
            episode_local_id=self.episode_local_id,
        )
        if target.as_record() != self.as_record():
            raise ValueError("workspace target identity is stale")

    def identity_record(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "artifact_id": self.artifact_id,
            "artifact_hash": self.artifact_hash,
            "json_pointer": self.json_pointer,
            "episode_local_id": self.episode_local_id,
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "content_hash": self.content_hash,
            **self.identity_record(),
        }

    @classmethod
    def create(
        cls,
        *,
        layer: str,
        artifact_id: str,
        artifact_hash: str,
        json_pointer: str,
        episode_local_id: Optional[str],
    ) -> "WorkspaceTarget":
        try:
            target_layer = RefinementTargetLayer(layer)
        except (TypeError, ValueError) as exc:
            raise ValueError("workspace target layer is invalid") from exc
        return cls.from_record(
            RefinementTarget(
                layer=target_layer,
                artifact_id=OpaqueId(artifact_id),
                artifact_hash=Sha256Digest(artifact_hash),
                json_pointer=json_pointer,
                episode_local_id=episode_local_id,
            ).as_record()
        )

    @classmethod
    def from_record(cls, value: object) -> "WorkspaceTarget":
        record = _mapping(value, "workspace target")
        expected = {
            "target_id",
            "content_hash",
            "layer",
            "artifact_id",
            "artifact_hash",
            "json_pointer",
            "episode_local_id",
        }
        if set(record) != expected:
            raise ValueError("workspace target fields are malformed")
        target = RefinementTarget.from_record(record)
        return cls(
            target_id=target.target_id.value,
            content_hash=target.content_hash.value,
            layer=target.layer.value,
            artifact_id=target.artifact_id.value,
            artifact_hash=target.artifact_hash.value,
            json_pointer=target.json_pointer,
            episode_local_id=target.episode_local_id,
        )


@dataclass(frozen=True)
class WorkspaceNote:
    """One host-persisted human note bound to an exact workspace target."""

    note_id: str
    content_hash: str
    duet_id: str
    baseline_id: Optional[str]
    human_authority_id: str
    target: WorkspaceTarget
    body: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, WorkspaceTarget):
            raise ValueError("workspace note target is invalid")
        note = DuetWorkspaceNote(
            duet_id=OpaqueId(self.duet_id),
            baseline_id=(
                None if self.baseline_id is None else OpaqueId(self.baseline_id)
            ),
            human_authority_id=OpaqueId(self.human_authority_id),
            body=self.body,
            target=RefinementTarget.from_record(self.target.as_record()),
        )
        if note.as_record() != self.as_record():
            raise ValueError("workspace note identity is stale")

    def identity_record(self) -> dict[str, Any]:
        return {
            "duet_id": self.duet_id,
            "baseline_id": self.baseline_id,
            "human_authority_id": self.human_authority_id,
            "body": self.body,
            "target": self.target.as_record(),
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "content_hash": self.content_hash,
            **self.identity_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "WorkspaceNote":
        record = _mapping(value, "workspace note")
        if set(record) != {
            "note_id",
            "content_hash",
            "duet_id",
            "baseline_id",
            "human_authority_id",
            "target",
            "body",
        }:
            raise ValueError("workspace note fields are malformed")
        note = DuetWorkspaceNote.from_record(record)
        return cls(
            note_id=note.note_id.value,
            content_hash=note.content_hash.value,
            duet_id=note.duet_id.value,
            baseline_id=(
                None if note.baseline_id is None else note.baseline_id.value
            ),
            human_authority_id=note.human_authority_id.value,
            target=WorkspaceTarget.from_record(note.target.as_record()),
            body=note.body,
        )


@dataclass(frozen=True)
class WorkspacePart:
    key: str
    label: str
    description: str
    summary: str
    declaration: object
    evidence: object
    part_hash: str
    target: Optional[WorkspaceTarget]
    code: Optional[str] = None
    editable: bool = False
    changed: bool = False
    incomplete: bool = False


@dataclass
class WorkspaceEpisode:
    local_id: str
    name: str
    parent_local_id: Optional[str]
    raw: dict[str, Any]
    target: WorkspaceTarget
    parts: tuple[WorkspacePart, ...]
    children: list["WorkspaceEpisode"] = field(default_factory=list)
    changed: bool = False


@dataclass(frozen=True)
class WorkspaceEntry:
    kind: str
    depth: int
    episode: Optional[WorkspaceEpisode] = None
    part: Optional[WorkspacePart] = None

    @property
    def target(self) -> Optional[WorkspaceTarget]:
        if self.part is not None:
            return self.part.target
        if self.episode is not None:
            return self.episode.target
        raise ValueError("workspace entry has no target")

    @property
    def selection_key(self) -> tuple[str, str, str]:
        if self.kind == "global" and self.part is not None:
            return ("global", "", self.part.key)
        if self.episode is None:
            raise ValueError("workspace entry has no Episode identity")
        if self.part is None:
            return ("episode", self.episode.local_id, "")
        return ("part", self.episode.local_id, self.part.key)


@dataclass(frozen=True)
class WorkspaceDetail:
    heading: str
    description: str
    summary: str
    declaration: str
    code: str
    evidence: str
    target: Optional[WorkspaceTarget]
    editable: bool

    def page(self, name: str) -> str:
        return {
            "summary": self.summary,
            "declaration": self.declaration,
            "code": self.code,
            "evidence": self.evidence,
        }[name]


class _EpisodeTreeViewModel:
    """Shared tree mechanics for the two concrete Episode projections."""

    surface: str
    title: str

    def __init__(self) -> None:
        self.global_parts: tuple[WorkspacePart, ...] = ()
        self.roots: list[WorkspaceEpisode] = []
        self._episodes: dict[str, WorkspaceEpisode] = {}
        self.expanded_episode_ids: set[str] = set()

    def _install_episodes(self, episodes: list[WorkspaceEpisode]) -> None:
        by_id = {item.local_id: item for item in episodes}
        if len(by_id) != len(episodes):
            raise ValueError("workspace Episode local IDs must be unique")
        roots: list[WorkspaceEpisode] = []
        for episode in episodes:
            parent_id = episode.parent_local_id
            if parent_id is None:
                roots.append(episode)
            elif parent_id not in by_id:
                raise ValueError(
                    f"Episode {episode.local_id!r} names unknown parent {parent_id!r}"
                )
            else:
                by_id[parent_id].children.append(episode)
        visited: set[str] = set()
        active: set[str] = set()

        def visit(item: WorkspaceEpisode) -> None:
            if item.local_id in active:
                raise ValueError("workspace Episode hierarchy contains a cycle")
            if item.local_id in visited:
                return
            active.add(item.local_id)
            for child in item.children:
                visit(child)
            active.remove(item.local_id)
            visited.add(item.local_id)

        for root in roots:
            visit(root)
        if len(visited) != len(episodes):
            raise ValueError("workspace Episode hierarchy contains a cycle")
        self.roots = roots
        self._episodes = by_id
        if not self.expanded_episode_ids:
            self.expanded_episode_ids = {item.local_id for item in roots}
        else:
            self.expanded_episode_ids.intersection_update(by_id)

    def visible_entries(self) -> list[WorkspaceEntry]:
        entries: list[WorkspaceEntry] = [
            WorkspaceEntry("global", 0, part=part)
            for part in self.global_parts
        ]

        def visit(episode: WorkspaceEpisode, depth: int) -> None:
            entries.append(WorkspaceEntry("episode", depth, episode=episode))
            if episode.local_id not in self.expanded_episode_ids:
                return
            entries.extend(
                WorkspaceEntry("part", depth + 1, episode=episode, part=part)
                for part in episode.parts
            )
            for child in episode.children:
                visit(child, depth + 1)

        for root in self.roots:
            visit(root, 0)
        return entries

    def toggle(
        self,
        episode: WorkspaceEpisode,
        *,
        expanded: Optional[bool] = None,
    ) -> None:
        current = episode.local_id in self.expanded_episode_ids
        desired = not current if expanded is None else expanded
        if desired:
            self.expanded_episode_ids.add(episode.local_id)
        else:
            self.expanded_episode_ids.discard(episode.local_id)

    def index_for_episode(self, local_id: str) -> int:
        entries = self.visible_entries()
        for index, entry in enumerate(entries):
            if entry.episode is not None and entry.episode.local_id == local_id:
                return index
        return 0

    def episode_target(self, episode: WorkspaceEpisode) -> WorkspaceTarget:
        return episode.target

    def detail_for(self, entry: WorkspaceEntry) -> WorkspaceDetail:
        if entry.part is not None:
            part = entry.part
            heading = part.label
            if entry.episode is not None:
                heading = f"{entry.episode.name} / {part.label}"
            return WorkspaceDetail(
                heading=heading,
                description=part.description,
                summary=part.summary,
                declaration=json.dumps(
                    part.declaration,
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                code=(
                    part.code
                    if part.code is not None
                    else "No generated source is attached to this part."
                ),
                evidence=json.dumps(
                    {
                        "part_key": part.key,
                        "part_hash": part.part_hash,
                        "target": (
                            None
                            if part.target is None
                            else part.target.as_record()
                        ),
                        "evidence": part.evidence,
                    },
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                target=part.target,
                editable=part.editable,
            )
        if entry.episode is None:
            raise ValueError("workspace entry is missing its Episode")
        episode = entry.episode
        target = episode.target
        return WorkspaceDetail(
            heading=episode.name,
            description="Episode navigation node and immediate topology.",
            summary=(
                f"Episode {episode.local_id}\n"
                f"Parent: {episode.parent_local_id or '-'}\n"
                f"Children: {', '.join(child.local_id for child in episode.children) or '-'}"
            ),
            declaration=json.dumps(
                episode.raw,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            ),
            code="Choose a materialized source part to inspect code.",
            evidence=json.dumps(
                target.as_record(),
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            ),
            target=target,
            editable=False,
        )


class WorkflowArchitectureViewModel(_EpisodeTreeViewModel):
    """Editable projection of one persisted Duet workflow draft."""

    surface = ARCHITECTURE_SURFACE
    title = "Workflow Architecture"

    def __init__(
        self,
        snapshot: Mapping[str, Any],
        *,
        changed_paths: tuple[str, ...] = (),
        missing_value: str = DEFAULT_MISSING_VALUE,
    ) -> None:
        super().__init__()
        snapshot = _mapping(snapshot, "architecture snapshot")
        required = {
            "source_artifact_id",
            "content_hash",
            "workflow_hash",
            "revision",
            "configuration",
            "validation_deficits",
            "editable",
            "pending_refinement",
        }
        if set(snapshot) != required:
            raise ValueError(
                "architecture snapshot has an invalid persisted shape"
            )
        self.source_artifact_id = _text(
            snapshot["source_artifact_id"],
            "architecture source_artifact_id",
        )
        self.content_hash = _text(
            snapshot["content_hash"],
            "architecture content_hash",
        )
        self.workflow_hash = _optional_text(
            snapshot["workflow_hash"],
            "architecture workflow_hash",
        )
        if self.workflow_hash is not None:
            Sha256Digest(self.workflow_hash)
        revision = snapshot["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("architecture revision must be a positive integer")
        self.revision = revision
        if not isinstance(snapshot["editable"], bool):
            raise ValueError("architecture editable must be boolean")
        self.host_editable = snapshot["editable"]
        pending_refinement = snapshot["pending_refinement"]
        if pending_refinement is not None:
            pending_refinement = _json_copy(
                _mapping(
                    pending_refinement,
                    "architecture pending_refinement",
                )
            )
        self.pending_refinement = pending_refinement
        deficits = snapshot["validation_deficits"]
        if not isinstance(deficits, (list, tuple)):
            raise ValueError("architecture validation_deficits must be an array")
        self.validation_deficits = tuple(_json_copy(deficits))
        if any(
            not isinstance(path, str)
            or "\x00" in path
            or (path and not path.startswith("/"))
            for path in changed_paths
        ):
            raise ValueError(
                "architecture changed_paths must be normalized JSON pointers"
            )
        self.changed_paths = frozenset(changed_paths)
        self.missing_value = _text(missing_value, "missing_value")
        configuration = _mapping(
            snapshot["configuration"],
            "architecture configuration",
        )
        self.document = _json_copy(configuration)
        self._original = _canonical(self.document)
        self._rebuild()

    @property
    def dirty(self) -> bool:
        return _canonical(self.document) != self._original

    def result(self) -> dict[str, Any]:
        return deepcopy(self.document)

    def _contains_missing(self, value: object) -> bool:
        if value == self.missing_value:
            return True
        if isinstance(value, Mapping):
            return any(self._contains_missing(item) for item in value.values())
        if isinstance(value, list):
            return any(self._contains_missing(item) for item in value)
        return False

    def _part_changed(self, pointer: str) -> bool:
        return any(
            changed == pointer
            or changed.startswith(pointer + "/")
            or pointer.startswith(changed + "/")
            for changed in self.changed_paths
        )

    def _target(
        self,
        local_id: Optional[str],
        json_pointer: str,
    ) -> WorkspaceTarget:
        return WorkspaceTarget.create(
            layer="workflow_semantics",
            artifact_id=self.source_artifact_id,
            artifact_hash=self.content_hash,
            json_pointer=json_pointer,
            episode_local_id=local_id,
        )

    def _architecture_part(
        self,
        *,
        local_id: str,
        key: str,
        label: str,
        description: str,
        payload: Mapping[str, Any],
        paths: tuple[str, ...],
        json_pointer: str,
        editable: bool,
    ) -> WorkspacePart:
        summary_lines = [f"{name}: {value}" for name, value in payload.items()]
        return WorkspacePart(
            key=key,
            label=label,
            description=description,
            summary="\n".join(summary_lines),
            declaration=_json_copy(payload),
            evidence={
                "source_artifact_id": self.source_artifact_id,
                "content_hash": self.content_hash,
                "workflow_hash": self.workflow_hash,
                "revision": self.revision,
                "paths": list(paths),
            },
            part_hash=_digest(payload),
            target=self._target(local_id, json_pointer),
            editable=editable,
            changed=self._part_changed(json_pointer),
            incomplete=self._contains_missing(payload),
        )

    def _rebuild_global_parts(self) -> None:
        overview = {
            "source_artifact_id": self.source_artifact_id,
            "content_hash": self.content_hash,
            "workflow_hash": self.workflow_hash,
            "revision": self.revision,
            "editable": self.host_editable,
        }
        validation = {
            "persisted_revision": self.revision,
            "validation_deficits": list(self.validation_deficits),
        }
        parts = [
            WorkspacePart(
                key="workflow_overview",
                label="Workflow overview",
                description=(
                    "Exact persisted architecture identity and edit authority."
                ),
                summary=(
                    f"Revision: {self.revision}\n"
                    f"Workflow hash: {self.workflow_hash or '-'}\n"
                    f"Host editable: {'yes' if self.host_editable else 'no'}"
                ),
                declaration=_json_copy(overview),
                evidence={
                    "source_artifact_id": self.source_artifact_id,
                    "content_hash": self.content_hash,
                },
                part_hash=_digest(overview),
                target=self._target(None, ""),
                changed=bool(self.changed_paths),
            ),
            WorkspacePart(
                key="workflow_validation",
                label="Workflow validation",
                description=(
                    "Host validation findings for this exact persisted revision."
                ),
                summary=(
                    "Host validation passed for the persisted revision."
                    if not self.validation_deficits
                    else (
                        f"{len(self.validation_deficits)} host validation "
                        "deficit(s) are attached."
                    )
                ),
                declaration=_json_copy(validation),
                evidence={
                    "source_artifact_id": self.source_artifact_id,
                    "revision": self.revision,
                    "finding_count": len(self.validation_deficits),
                },
                part_hash=_digest(validation),
                target=None,
                incomplete=bool(self.validation_deficits),
            ),
        ]
        if self.pending_refinement is not None:
            kind = self.pending_refinement.get("change_kind", "pending")
            parts.append(
                WorkspacePart(
                    key="pending_refinement",
                    label="Pending refinement",
                    description=(
                        "Immutable proposal awaiting explicit human approval or decline."
                    ),
                    summary=f"Change kind: {kind}",
                    declaration=_json_copy(self.pending_refinement),
                    evidence={
                        "decision_id": self.pending_refinement.get(
                            "decision_id"
                        ),
                        "decision_hash": self.pending_refinement.get(
                            "decision_hash"
                        ),
                    },
                    part_hash=_digest(self.pending_refinement),
                    target=None,
                    changed=True,
                )
            )
        self.global_parts = tuple(parts)

    def _rebuild(self) -> None:
        self._rebuild_global_parts()
        raw_episodes = self.document.get("episodes")
        if not isinstance(raw_episodes, list) or not raw_episodes:
            raise ValueError(
                "architecture configuration requires a non-empty episodes array"
            )
        episodes: list[WorkspaceEpisode] = []
        for index, raw_value in enumerate(raw_episodes):
            raw = _mapping(raw_value, f"architecture Episode {index + 1}")
            contract = _mapping(
                raw.get("contract"),
                f"architecture Episode {index + 1} contract",
            )
            local_id = _text(
                raw.get("local_id"),
                f"architecture Episode {index + 1} local_id",
            )
            parent = _optional_text(
                raw.get("workflow_parent_local_id"),
                f"architecture Episode {local_id} parent",
            )
            episode_pointer = "/episodes/" + _pointer_token(local_id)
            contract_pointer = episode_pointer + "/contract"
            part_definitions = (
                (
                    "local_id",
                    "Episode ID",
                    "Stable Episode identity used throughout the nested workflow.",
                    local_id,
                    episode_pointer + "/local_id",
                    False,
                ),
                (
                    "workflow_parent_local_id",
                    "Parent Episode",
                    "Stable parent identity that places this Episode in the workflow tree.",
                    parent,
                    episode_pointer + "/workflow_parent_local_id",
                    False,
                ),
                (
                    "goal",
                    "Goal",
                    "Outcome this Episode is responsible for advancing.",
                    contract.get("goal"),
                    contract_pointer + "/goal",
                    True,
                ),
                (
                    "result",
                    "Result",
                    "Concrete result this Episode returns to its parent.",
                    contract.get("result"),
                    contract_pointer + "/result",
                    True,
                ),
                (
                    "unit",
                    "Loop unit",
                    "One repeatable unit of work performed by this Episode.",
                    contract.get("unit"),
                    contract_pointer + "/unit",
                    True,
                ),
                (
                    "progress",
                    "Progress",
                    "Measured progress produced by each loop unit.",
                    contract.get("progress"),
                    contract_pointer + "/progress",
                    True,
                ),
                (
                    "stopping",
                    "Stopping semantics",
                    "Numerical continuation and stopping semantics for the measured sequence.",
                    contract.get("stopping"),
                    contract_pointer + "/stopping",
                    True,
                ),
                (
                    "numeric_control",
                    "Numerical control",
                    (
                        "Exact registered rarefaction and continuation function "
                        "pointers with their human-approved arguments."
                    ),
                    contract["numeric_control"],
                    contract_pointer + "/numeric_control",
                    True,
                ),
                (
                    "execution_capability_names",
                    "Execution capabilities",
                    "Explicit capabilities available inside this Episode boundary.",
                    contract.get("execution_capability_names"),
                    contract_pointer + "/execution_capability_names",
                    True,
                ),
                (
                    "egress_allowlist",
                    "External requests",
                    (
                        "Read-only HTTPS endpoints this Episode may call through "
                        "the host broker, with budgets and credential names."
                    ),
                    contract.get("egress_allowlist"),
                    contract_pointer + "/egress_allowlist",
                    True,
                ),
                (
                    "deliverable",
                    "Deliverable",
                    "Closed result form emitted by this Episode.",
                    contract.get("deliverable"),
                    contract_pointer + "/deliverable",
                    True,
                ),
                (
                    "episode_reference",
                    "Reference Episode",
                    "Optional durable Episode-library reference used as implementation evidence.",
                    raw.get("episode_reference"),
                    episode_pointer + "/episode_reference",
                    True,
                ),
            )
            parts = tuple(
                self._architecture_part(
                    local_id=local_id,
                    key=key,
                    label=label,
                    description=description,
                    payload={key: value},
                    paths=(
                        key
                        if key in {"local_id", "workflow_parent_local_id", "episode_reference"}
                        else "contract." + key,
                    ),
                    json_pointer=json_pointer,
                    editable=editable,
                )
                for key, label, description, value, json_pointer, editable in part_definitions
            )
            goal = contract.get("goal")
            name = local_id
            if isinstance(goal, str) and goal.strip() and goal != self.missing_value:
                compact = " ".join(goal.split())
                name = compact if len(compact) <= 46 else compact[:43].rstrip() + "..."
            episodes.append(
                WorkspaceEpisode(
                    local_id=local_id,
                    name=name,
                    parent_local_id=parent,
                    raw=_json_copy(raw),
                    target=self._target(
                        local_id,
                        "/episodes/" + _pointer_token(local_id),
                    ),
                    parts=parts,
                    changed=self._part_changed(episode_pointer),
                )
            )
        self._install_episodes(episodes)

    def episode_target(self, episode: WorkspaceEpisode) -> WorkspaceTarget:
        return episode.target

    def apply_part(
        self,
        episode_local_id: str,
        part_key: str,
        payload: object,
    ) -> None:
        payload = _mapping(payload, "architecture edit")
        episode = self._episodes.get(episode_local_id)
        if episode is None:
            raise ValueError("architecture edit names an unknown Episode")
        part = next((item for item in episode.parts if item.key == part_key), None)
        if part is None or not part.editable:
            raise ValueError("selected architecture part is not editable")
        expected = set(_mapping(part.declaration, "part declaration"))
        if set(payload) != expected:
            raise ValueError(
                f"{part.label} fields must remain exactly {sorted(expected)!r}"
            )
        raw = self.document["episodes"][
            next(
                index
                for index, item in enumerate(self.document["episodes"])
                if item["local_id"] == episode_local_id
            )
        ]
        contract = raw["contract"]
        contract_keys = {
            "goal",
            "result",
            "unit",
            "progress",
            "stopping",
            "numeric_control",
            "execution_capability_names",
            "egress_allowlist",
            "deliverable",
        }
        if part_key in contract_keys:
            contract[part_key] = _json_copy(payload[part_key])
        elif part_key == "episode_reference":
            raw[part_key] = _json_copy(payload[part_key])
        else:
            raise ValueError("unsupported architecture edit")
        self._rebuild()


class MaterializedSpecificationViewModel(_EpisodeTreeViewModel):
    """Read-only host projection of one persisted materialization.

    Builder records, package paths, source parsing, and artifact crosswalks are
    host responsibilities.  This view accepts already projected display parts
    whose exact targets and evidence are explicit, and validates only that
    closed projection.
    """

    surface = MATERIALIZED_SURFACE
    title = "Materialized Specification"

    def __init__(
        self,
        snapshot: Mapping[str, Any],
        *,
        changed_paths: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        snapshot = _mapping(snapshot, "materialized snapshot")
        expected = {
            "anchor_artifact_id",
            "anchor_hash",
            "workflow_hash",
            "status",
            "global_parts",
            "episodes",
            "build_chain",
            "crosswalk",
        }
        if set(snapshot) != expected:
            raise ValueError(
                "materialized snapshot has an invalid host projection shape"
            )
        self.anchor_artifact_id = _text(
            snapshot["anchor_artifact_id"],
            "materialized anchor_artifact_id",
        )
        self.anchor_hash = _text(
            snapshot["anchor_hash"],
            "materialized anchor_hash",
        )
        self.workflow_hash = _text(
            snapshot["workflow_hash"],
            "materialized workflow_hash",
        )
        Sha256Digest(self.workflow_hash)
        self.status = _text(snapshot["status"], "materialized status")
        if any(
            not isinstance(path, str)
            or "\x00" in path
            or (path and not path.startswith("/"))
            for path in changed_paths
        ):
            raise ValueError(
                "materialized changed_paths must be normalized JSON pointers"
            )
        self.changed_paths = frozenset(changed_paths)
        self.build_chain = self._build_chain(snapshot["build_chain"])
        self.crosswalk = _json_copy(
            _mapping(snapshot["crosswalk"], "materialized crosswalk")
        )
        raw_global_parts = snapshot["global_parts"]
        raw_episodes = snapshot["episodes"]
        if not isinstance(raw_global_parts, list) or not raw_global_parts:
            raise ValueError(
                "materialized projection requires at least one workflow-global part"
            )
        if not isinstance(raw_episodes, list):
            raise ValueError("materialized episodes must be an array")
        self.global_parts = self._parts(
            raw_global_parts,
            episode_local_id=None,
            name="materialized global_parts",
            collection_pointer="/global_parts",
        )
        episodes = [
            self._episode(value, index)
            for index, value in enumerate(raw_episodes)
        ]
        all_targets = [part.target.target_id for part in self.global_parts]
        for episode in episodes:
            all_targets.append(episode.target.target_id)
            all_targets.extend(part.target.target_id for part in episode.parts)
        if len(set(all_targets)) != len(all_targets):
            raise ValueError("materialized projection target IDs must be unique")
        self._install_episodes(episodes)

    def _part_changed(self, pointer: str) -> bool:
        return any(
            changed == pointer
            or changed.startswith(pointer + "/")
            or pointer.startswith(changed + "/")
            for changed in self.changed_paths
        )

    @staticmethod
    def _build_chain(value: object) -> dict[str, Any]:
        record = _mapping(value, "materialized build_chain")
        expected = {
            "build_receipt_id",
            "build_receipt_hash",
            "build_manifest_id",
            "build_manifest_hash",
        }
        if set(record) != expected:
            raise ValueError("materialized build_chain has an invalid shape")
        receipt_id = _text(
            record["build_receipt_id"],
            "materialized build_receipt_id",
        )
        receipt_hash = _text(
            record["build_receipt_hash"],
            "materialized build_receipt_hash",
        )
        OpaqueId(receipt_id)
        Sha256Digest(receipt_hash)
        manifest_id = _optional_text(
            record["build_manifest_id"],
            "materialized build_manifest_id",
        )
        manifest_hash = _optional_text(
            record["build_manifest_hash"],
            "materialized build_manifest_hash",
        )
        if (manifest_id is None) != (manifest_hash is None):
            raise ValueError(
                "materialized manifest identity and hash must both be present or absent"
            )
        if manifest_id is not None and manifest_hash is not None:
            OpaqueId(manifest_id)
            Sha256Digest(manifest_hash)
        return {
            "build_receipt_id": receipt_id,
            "build_receipt_hash": receipt_hash,
            "build_manifest_id": manifest_id,
            "build_manifest_hash": manifest_hash,
        }

    def _target(
        self,
        value: object,
        *,
        episode_local_id: Optional[str],
        name: str,
    ) -> WorkspaceTarget:
        target = WorkspaceTarget.from_record(value)
        if target.layer != "materialization_implementation":
            raise ValueError(f"{name} target belongs to another refinement layer")
        if (
            target.artifact_id != self.anchor_artifact_id
            or target.artifact_hash != self.anchor_hash
        ):
            raise ValueError(
                f"{name} target is not anchored to the projected Materialized Specification"
            )
        if target.episode_local_id != episode_local_id:
            raise ValueError(f"{name} target Episode identity differs from its row")
        return target

    def _part(
        self,
        value: object,
        *,
        episode_local_id: Optional[str],
        name: str,
        collection_pointer: str,
    ) -> WorkspacePart:
        record = _mapping(value, name)
        expected = {
            "key",
            "label",
            "description",
            "summary",
            "declaration",
            "evidence",
            "part_hash",
            "target",
            "code",
        }
        if set(record) != expected:
            raise ValueError(f"{name} has an invalid projected-part shape")
        code = record["code"]
        if code is not None:
            code = _text(code, f"{name} code", allow_empty=True)
        key = _text(record["key"], f"{name} key")
        target = self._target(
            record["target"],
            episode_local_id=episode_local_id,
            name=name,
        )
        if episode_local_id is not None and not target.json_pointer:
            raise ValueError(f"{name} target must identify an exact projected part")
        part_hash = _text(record["part_hash"], f"{name} part_hash")
        Sha256Digest(part_hash)
        return WorkspacePart(
            key=key,
            label=_text(record["label"], f"{name} label"),
            description=_text(
                record["description"],
                f"{name} description",
                allow_empty=True,
            ),
            summary=_text(
                record["summary"],
                f"{name} summary",
                allow_empty=True,
            ),
            declaration=_json_copy(record["declaration"]),
            evidence=_json_copy(record["evidence"]),
            part_hash=part_hash,
            target=target,
            code=code,
            changed=self._part_changed(
                collection_pointer + "/" + _pointer_token(key)
            ),
        )

    def _parts(
        self,
        values: object,
        *,
        episode_local_id: Optional[str],
        name: str,
        collection_pointer: str,
    ) -> tuple[WorkspacePart, ...]:
        if not isinstance(values, list):
            raise ValueError(f"{name} must be an array")
        parts = tuple(
            self._part(
                value,
                episode_local_id=episode_local_id,
                name=f"{name}[{index}]",
                collection_pointer=collection_pointer,
            )
            for index, value in enumerate(values)
        )
        keys = [part.key for part in parts]
        if len(set(keys)) != len(keys):
            raise ValueError(f"{name} keys must be unique")
        return parts

    def _episode(self, value: object, index: int) -> WorkspaceEpisode:
        name = f"materialized episodes[{index}]"
        record = _mapping(value, name)
        expected = {
            "local_id",
            "name",
            "parent_local_id",
            "declaration",
            "target",
            "parts",
        }
        if set(record) != expected:
            raise ValueError(f"{name} has an invalid projected-Episode shape")
        local_id = _text(record["local_id"], f"{name} local_id")
        episode_pointer = "/episodes/" + _pointer_token(local_id)
        target = self._target(
            record["target"],
            episode_local_id=local_id,
            name=name,
        )
        if not target.json_pointer:
            raise ValueError(f"{name} navigation target must identify its Episode")
        return WorkspaceEpisode(
            local_id=local_id,
            name=_text(record["name"], f"{name} name"),
            parent_local_id=_optional_text(
                record["parent_local_id"],
                f"{name} parent_local_id",
            ),
            raw=_json_copy(_mapping(record["declaration"], f"{name} declaration")),
            target=target,
            parts=self._parts(
                record["parts"],
                episode_local_id=local_id,
                name=f"{name} parts",
                collection_pointer=episode_pointer + "/parts",
            ),
            changed=self._part_changed(episode_pointer),
        )


def notes_from_records(values: object) -> tuple[WorkspaceNote, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("workspace notes must be an array")
    notes = tuple(WorkspaceNote.from_record(value) for value in values)
    by_id = {note.note_id: note for note in notes}
    if len(by_id) != len(notes):
        raise ValueError("workspace note IDs must be unique")
    return notes


__all__ = [
    "ARCHITECTURE_SURFACE",
    "DEFAULT_MISSING_VALUE",
    "MATERIALIZED_SURFACE",
    "MaterializedSpecificationViewModel",
    "WorkflowArchitectureViewModel",
    "WorkspaceDetail",
    "WorkspaceEntry",
    "WorkspaceNote",
    "WorkspaceTarget",
    "notes_from_records",
]
