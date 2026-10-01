"""Focused tree editor for OpenChia Episode and workflow blueprints."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Any, Mapping, Optional

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Dimension, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Button, Frame, TextArea


@dataclass(frozen=True)
class EpisodeSection:
    key: str
    label: str
    description: str
    paths: tuple[tuple[str, ...], ...]


_BASE_SECTIONS = (
    EpisodeSection(
        "goal",
        "Goal",
        "Edit the stable outcome and the concrete result this Episode must produce.",
        (("goal",), ("result",)),
    ),
    EpisodeSection(
        "planning",
        "Planning",
        "Edit the repeatable unit and its host-observable progress measurement.",
        (("unit",), ("progress",)),
    ),
    EpisodeSection(
        "task",
        "Task",
        "Edit the execution capabilities and deliverable contract.",
        (("execution_capability_names",), ("deliverable",)),
    ),
)

_CREDIT_SECTION = EpisodeSection(
    "credit_assignment",
    "Credit assignment",
    "Edit evidence requirements, weighted credit, and the typed return contract.",
    (
        ("creator_contract", "evidence_requirements"),
        ("creator_contract", "credit_assignment"),
        ("creator_contract", "return_contract"),
    ),
)

_RAREFACTION_SECTION = EpisodeSection(
    "rarefaction",
    "Rarefaction",
    "Edit the target, minimum useful yield, and stagnation observation window.",
    (("stopping",),),
)

_SAFETY_SECTION = EpisodeSection(
    "safety",
    "Safety bounds",
    "Edit iteration, child, depth, and elapsed-time limits.",
    (("safety_bounds",),),
)

_AUTHORITY_SECTION = EpisodeSection(
    "creator_authority",
    "Creator authority",
    "Edit structured context and the exact capability ceiling for child Episodes.",
    (
        ("creator_contract", "design_context"),
        ("creator_contract", "design_scope"),
        ("creator_contract", "assignable_capability_names"),
        ("creator_contract", "may_assign_creator_capability"),
        ("creator_contract", "required_existing_evidence_ids"),
    ),
)

_UNSET_CREATOR_SECTION = EpisodeSection(
    "creator_contract",
    "Creation authority · none",
    "This is an ordinary task Episode. Replace null with a complete Creator "
    "contract only when this Episode must design child Episodes at runtime.",
    (("creator_contract",),),
)


@dataclass
class EpisodeNode:
    node_id: str
    name: str
    document_index: int
    contract: dict[str, Any]
    children: list["EpisodeNode"] = field(default_factory=list)


@dataclass(frozen=True)
class EpisodeTreeEntry:
    kind: str
    depth: int
    episode: EpisodeNode
    section: Optional[EpisodeSection] = None


def _mapping_at(value: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            raise ValueError(f"Episode section path is missing: {'.'.join(path)}")
        current = current[part]
    return current


def _set_at(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> None:
    current = value
    for part in path[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            raise ValueError(f"Episode section path is not an object: {'.'.join(path[:-1])}")
        current = child
    current[path[-1]] = replacement


class EpisodeEditorModel:
    """Mutable working copy projected as Episodes and named design sections."""

    def __init__(
        self,
        document: Mapping[str, Any],
        *,
        missing_value: str,
        changed_paths: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(document, Mapping):
            raise TypeError("Episode editor document must be an object")
        self.document: dict[str, Any] = deepcopy(dict(document))
        self.missing_value = missing_value
        self.changed_paths = frozenset(changed_paths)
        self.roots = self._episode_roots()
        self.expanded_episode_ids = {node.node_id for node in self.roots}

    @staticmethod
    def _walk_episodes(roots: list[EpisodeNode]) -> list[EpisodeNode]:
        found: list[EpisodeNode] = []

        def visit(node: EpisodeNode) -> None:
            found.append(node)
            for child in node.children:
                visit(child)

        for root in roots:
            visit(root)
        return found

    def _episode_name(
        self,
        raw: Mapping[str, Any],
        contract: Mapping[str, Any],
        index: int,
    ) -> str:
        for key in ("name", "local_id", "instance_id"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        goal = contract.get("goal")
        if isinstance(goal, str) and goal.strip() and goal != self.missing_value:
            compact = " ".join(goal.split())
            return compact if len(compact) <= 42 else compact[:39].rstrip() + "..."
        return f"Episode {index + 1}"

    def _episode_roots(self) -> list[EpisodeNode]:
        raw_episodes = self.document.get("episodes")
        if not isinstance(raw_episodes, list):
            raise ValueError(
                "Episode editor requires a workflow document with an episodes array"
            )
        if not raw_episodes:
            raise ValueError("Episode workflow must contain at least one Episode")

        nodes: dict[str, EpisodeNode] = {}
        parent_ids: dict[str, Optional[str]] = {}
        ordered_ids: list[str] = []
        for index, raw in enumerate(raw_episodes):
            if not isinstance(raw, dict) or not isinstance(raw.get("contract"), dict):
                raise ValueError(f"workflow Episode {index + 1} has no editable contract")
            raw_id = raw.get("local_id")
            node_id = raw_id if isinstance(raw_id, str) and raw_id else f"episode_{index + 1}"
            if node_id in nodes:
                raise ValueError(f"duplicate workflow Episode name: {node_id}")
            contract = raw["contract"]
            nodes[node_id] = EpisodeNode(
                node_id=node_id,
                name=self._episode_name(raw, contract, index),
                document_index=index,
                contract=contract,
            )
            parent = raw.get("workflow_parent_local_id")
            parent_ids[node_id] = parent if isinstance(parent, str) and parent else None
            ordered_ids.append(node_id)

        roots: list[EpisodeNode] = []
        for node_id in ordered_ids:
            parent_id = parent_ids[node_id]
            if parent_id is None:
                roots.append(nodes[node_id])
            elif parent_id not in nodes:
                raise ValueError(
                    f"workflow Episode {node_id} names unknown parent {parent_id}"
                )
            else:
                nodes[parent_id].children.append(nodes[node_id])
        cycle = self._parent_cycle(parent_ids, ordered_ids)
        if cycle is not None:
            raise ValueError(
                "workflow Episode hierarchy contains a cycle: "
                + " -> ".join(cycle)
            )
        visited = self._walk_episodes(roots)
        if len(visited) != len(nodes) or len({node.node_id for node in visited}) != len(nodes):
            raise ValueError("workflow Episode hierarchy contains a cycle")
        return roots

    @staticmethod
    def _parent_cycle(
        parent_ids: Mapping[str, Optional[str]],
        ordered_ids: list[str],
    ) -> Optional[tuple[str, ...]]:
        resolved: set[str] = set()
        for start in ordered_ids:
            path: list[str] = []
            positions: dict[str, int] = {}
            cursor: Optional[str] = start
            while cursor is not None and cursor not in resolved:
                if cursor in positions:
                    offset = positions[cursor]
                    return tuple([*path[offset:], cursor])
                positions[cursor] = len(path)
                path.append(cursor)
                cursor = parent_ids.get(cursor)
            resolved.update(path)
        return None

    def episode_changed(self, episode: EpisodeNode) -> bool:
        prefix = f"episodes.{episode.document_index}"
        return any(
            path == prefix or path.startswith(prefix + ".")
            for path in self.changed_paths
        )

    def section_changed(
        self,
        episode: EpisodeNode,
        section: EpisodeSection,
    ) -> bool:
        base = f"episodes.{episode.document_index}.contract"
        for section_path in section.paths:
            prefix = f"{base}.{'.'.join(section_path)}"
            if any(
                path == prefix
                or path.startswith(prefix + ".")
                or prefix.startswith(path + ".")
                for path in self.changed_paths
            ):
                return True
        return False

    def sections_for(self, episode: EpisodeNode) -> tuple[EpisodeSection, ...]:
        sections = [*_BASE_SECTIONS]
        creator = episode.contract.get("creator_contract", self.missing_value)
        if isinstance(creator, Mapping):
            sections.append(_CREDIT_SECTION)
        elif creator != self.missing_value:
            sections.append(_UNSET_CREATOR_SECTION)
        sections.append(_RAREFACTION_SECTION)
        if isinstance(creator, Mapping):
            sections.append(_AUTHORITY_SECTION)
        sections.append(_SAFETY_SECTION)
        return tuple(sections)

    def visible_entries(self) -> list[EpisodeTreeEntry]:
        entries: list[EpisodeTreeEntry] = []

        def visit(episode: EpisodeNode, depth: int) -> None:
            entries.append(EpisodeTreeEntry("episode", depth, episode))
            if episode.node_id not in self.expanded_episode_ids:
                return
            entries.extend(
                EpisodeTreeEntry("section", depth + 1, episode, section)
                for section in self.sections_for(episode)
            )
            for child in episode.children:
                visit(child, depth + 1)

        for root in self.roots:
            visit(root, 0)
        return entries

    def toggle(self, episode: EpisodeNode, *, expanded: Optional[bool] = None) -> None:
        is_expanded = episode.node_id in self.expanded_episode_ids
        should_expand = not is_expanded if expanded is None else expanded
        if should_expand:
            self.expanded_episode_ids.add(episode.node_id)
        else:
            self.expanded_episode_ids.discard(episode.node_id)

    def section_payload(
        self,
        episode: EpisodeNode,
        section: EpisodeSection,
    ) -> dict[str, Any]:
        return {
            path[-1]: deepcopy(_mapping_at(episode.contract, path))
            for path in section.paths
        }

    def apply_section(
        self,
        episode: EpisodeNode,
        section: EpisodeSection,
        payload: object,
    ) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError(f"{section.label} must remain a JSON object")
        expected = {path[-1] for path in section.paths}
        actual = set(payload)
        if actual != expected:
            raise ValueError(
                f"{section.label} fields must be exactly {sorted(expected)}; "
                f"missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
            )
        for path in section.paths:
            _set_at(episode.contract, path, deepcopy(payload[path[-1]]))

    def section_complete(self, episode: EpisodeNode, section: EpisodeSection) -> bool:
        def contains_missing(value: Any) -> bool:
            if value == self.missing_value:
                return True
            if isinstance(value, Mapping):
                return any(contains_missing(item) for item in value.values())
            if isinstance(value, list):
                return any(contains_missing(item) for item in value)
            return False

        return not contains_missing(self.section_payload(episode, section))

    def result(self) -> dict[str, Any]:
        return deepcopy(self.document)


class EpisodeTreeEditor:
    """Full-screen keyboard and mouse tree for one Episode document."""

    def __init__(
        self,
        document: Mapping[str, Any],
        *,
        missing_value: str,
        read_only: bool = False,
        changed_paths: tuple[str, ...] = (),
        revision: Optional[int] = None,
        validation_deficits: tuple[Mapping[str, Any], ...] = (),
    ) -> None:
        self.model = EpisodeEditorModel(
            document,
            missing_value=missing_value,
            changed_paths=changed_paths,
        )
        self.read_only = read_only
        self.revision = revision
        self.validation_deficits = validation_deficits
        self.selected_index = 0
        self.selected_section: Optional[tuple[EpisodeNode, EpisodeSection]] = None
        self.status = "Select a section to inspect it."
        self._editable = False

        self.tree_control = FormattedTextControl(
            self._tree_fragments,
            focusable=True,
            get_cursor_position=lambda: Point(x=0, y=self.selected_index),
        )
        self.tree_window = Window(
            self.tree_control,
            width=Dimension(min=30, preferred=42),
            wrap_lines=False,
            right_margins=[],
        )
        self.editor = TextArea(
            multiline=True,
            scrollbar=True,
            wrap_lines=True,
            focus_on_click=True,
            read_only=Condition(lambda: not self._editable),
        )
        self.apply_button = Button("Apply section", handler=self._apply_button)
        self.save_button = Button("Save", handler=self._save)
        self.cancel_button = Button(
            "Close" if read_only else "Cancel",
            handler=self._cancel,
        )

        body = VSplit(
            [
                Frame(self.tree_window, title="Episode tree"),
                Frame(
                    HSplit(
                        [
                            Window(
                                FormattedTextControl(self._selection_heading),
                                height=2,
                                style="class:editor.heading",
                            ),
                            self.editor,
                        ]
                    ),
                    title="Focused editor",
                ),
            ],
            padding=1,
        )
        buttons = VSplit(
            (
                [self.cancel_button]
                if read_only
                else [self.apply_button, self.save_button, self.cancel_button]
            ),
            padding=2,
            height=1,
        )
        title = "OPENCHIA EPISODE VIEW" if read_only else "OPENCHIA EPISODE EDITOR"
        if validation_deficits:
            codes = [
                str(item.get("code") or "invalid_workflow")
                for item in validation_deficits
            ]
            state = f"checks failed: {codes[0]}"
            if len(codes) > 1:
                state += f" +{len(codes) - 1}"
        else:
            state = "checks passed"
        revision_label = "draft" if revision is None else f"r{revision}"
        changed_label = (
            "no changes since last view"
            if not changed_paths
            else f"{len(changed_paths)} changed value(s) since last view"
        )
        subtitle = f"{revision_label} · {state} · {changed_label}"
        root = HSplit(
            [
                Window(
                    FormattedTextControl(
                        f"{title}\n{subtitle}"
                    ),
                    height=2,
                    style="class:editor.title",
                ),
                body,
                buttons,
                Window(
                    FormattedTextControl(self._footer),
                    height=2,
                    style="class:editor.footer",
                ),
            ]
        )
        self.key_bindings = self._key_bindings()
        self.application: Application[dict[str, Any] | None] = Application(
            layout=Layout(root, focused_element=self.tree_window),
            key_bindings=self.key_bindings,
            full_screen=True,
            mouse_support=True,
            style=Style.from_dict(
                {
                    "editor.title": "bold fg:#8fb9a8",
                    "editor.heading": "bold fg:#c7ddd4",
                    "editor.footer": "fg:#9aa6a1",
                    "tree.episode": "bold fg:#d8eee5",
                    "tree.section": "fg:#b4c4be",
                    "tree.selected": "reverse",
                    "tree.missing": "fg:#e1b56f",
                    "tree.changed": "bold fg:#e1b56f",
                    "button": "fg:#d8eee5 bg:#33443e",
                    "button.focused": "bold fg:#17201d bg:#8fb9a8",
                    "frame.border": "fg:#60756d",
                }
            ),
        )
        self._load_selection(focus_editor=False)

    def _entries(self) -> list[EpisodeTreeEntry]:
        return self.model.visible_entries()

    def _mouse_handler(self, index: int):
        def handle(mouse_event: MouseEvent) -> None:
            if mouse_event.event_type is not MouseEventType.MOUSE_UP:
                return
            if self._select_index(index):
                entry = self._entries()[self.selected_index]
                if entry.kind == "episode":
                    self.model.toggle(entry.episode)
                    self.selected_index = min(
                        self.selected_index,
                        len(self._entries()) - 1,
                    )
                    self._load_selection(focus_editor=False)
                else:
                    get_app().layout.focus(self.editor)
                get_app().invalidate()

        return handle

    def _tree_fragments(self) -> AnyFormattedText:
        fragments: list[tuple[str, str, Any]] = []
        entries = self._entries()
        for index, entry in enumerate(entries):
            selected = index == self.selected_index
            style = "class:tree.episode" if entry.kind == "episode" else "class:tree.section"
            if entry.kind == "section" and entry.section is not None:
                if not self.model.section_complete(entry.episode, entry.section):
                    style += " class:tree.missing"
                if self.model.section_changed(entry.episode, entry.section):
                    style += " class:tree.changed"
            if selected:
                style += " class:tree.selected"
            indent = "   " * entry.depth
            if entry.kind == "episode":
                marker = (
                    "[-]"
                    if entry.episode.node_id in self.model.expanded_episode_ids
                    else "[+]"
                )
                changed = "  Δ" if self.model.episode_changed(entry.episode) else ""
                label = f"{indent}{marker} {entry.episode.name}{changed}\n"
            else:
                completeness = "" if self.model.section_complete(
                    entry.episode, entry.section
                ) else "  !"
                changed = (
                    "  Δ"
                    if self.model.section_changed(entry.episode, entry.section)
                    else ""
                )
                label = (
                    f"{indent}|- {entry.section.label}{completeness}{changed}\n"
                )
            fragments.append((style, label, self._mouse_handler(index)))
        return fragments

    def _selection_heading(self) -> AnyFormattedText:
        if self.selected_section is None:
            return "Episode overview\nExpand an Episode and choose one of its design sections."
        episode, section = self.selected_section
        return f"{episode.name} / {section.label}\n{section.description}"

    def _footer(self) -> AnyFormattedText:
        controls = (
            "Mouse or Up/Down: select  Enter: zoom/toggle  Ctrl+Q or Esc: close"
            if self.read_only
            else "Mouse or Up/Down: select  Enter: zoom/toggle  Ctrl+S: save  Ctrl+Q: cancel"
        )
        return (
            f"{self.status}\n"
            f"{controls}"
        )

    def _set_editor_text(self, text: str, *, editable: bool) -> None:
        self._editable = editable
        self.editor.buffer.set_document(
            Document(text, cursor_position=0),
            bypass_readonly=True,
        )

    def _load_selection(self, *, focus_editor: bool) -> None:
        entries = self._entries()
        if not entries:
            return
        self.selected_index = min(max(self.selected_index, 0), len(entries) - 1)
        entry = entries[self.selected_index]
        if entry.kind == "section" and entry.section is not None:
            self.selected_section = (entry.episode, entry.section)
            payload = self.model.section_payload(entry.episode, entry.section)
            self._set_editor_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                editable=not self.read_only,
            )
            verb = "Viewing" if self.read_only else "Editing"
            self.status = f"{verb} {entry.episode.name} / {entry.section.label}."
            if focus_editor:
                get_app().layout.focus(self.editor)
        else:
            self.selected_section = None
            self._set_editor_text(
                "This Episode is a navigation node.\n\n"
                "Expand it, then choose Goal, Planning, Task, Credit assignment, "
                "Rarefaction, or another relevant section.",
                editable=False,
            )
            self.status = f"Selected {entry.episode.name}."

    def _commit_section(self) -> bool:
        if self.read_only:
            return True
        if self.selected_section is None:
            return True
        text = self.editor.text.strip()
        try:
            payload = json.loads(text)
            episode, section = self.selected_section
            self.model.apply_section(episode, section, payload)
        except (json.JSONDecodeError, ValueError) as exc:
            self.status = f"Not applied: {exc}"
            get_app().layout.focus(self.editor)
            get_app().invalidate()
            return False
        self.status = f"Applied {episode.name} / {section.label}."
        return True

    def _select_index(self, index: int) -> bool:
        if index == self.selected_index:
            return True
        if not self._commit_section():
            return False
        entries = self._entries()
        self.selected_index = min(max(index, 0), len(entries) - 1)
        self._load_selection(focus_editor=False)
        return True

    def _move(self, delta: int) -> None:
        self._select_index(self.selected_index + delta)
        get_app().invalidate()

    def _activate_selection(self) -> None:
        entry = self._entries()[self.selected_index]
        if entry.kind == "episode":
            if not self._commit_section():
                return
            self.model.toggle(entry.episode)
            self.selected_index = min(self.selected_index, len(self._entries()) - 1)
            self._load_selection(focus_editor=False)
        else:
            self._load_selection(focus_editor=True)
        get_app().invalidate()

    def _apply_button(self) -> None:
        self._commit_section()
        get_app().invalidate()

    def _save(self) -> None:
        if self._commit_section():
            get_app().exit(result=self.model.result())

    @staticmethod
    def _cancel() -> None:
        get_app().exit(result=None)

    def _key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()
        tree_focused = has_focus(self.tree_window)

        @bindings.add("up", filter=tree_focused)
        def _up(_event) -> None:
            self._move(-1)

        @bindings.add("down", filter=tree_focused)
        def _down(_event) -> None:
            self._move(1)

        @bindings.add("enter", filter=tree_focused)
        def _enter(_event) -> None:
            self._activate_selection()

        @bindings.add("right", filter=tree_focused)
        def _right(_event) -> None:
            entry = self._entries()[self.selected_index]
            if entry.kind == "episode":
                self.model.toggle(entry.episode, expanded=True)
                self._load_selection(focus_editor=False)
                get_app().invalidate()

        @bindings.add("left", filter=tree_focused)
        def _left(_event) -> None:
            entry = self._entries()[self.selected_index]
            if entry.kind == "episode":
                self.model.toggle(entry.episode, expanded=False)
                self._load_selection(focus_editor=False)
                get_app().invalidate()

        @bindings.add("c-s")
        def _save(_event) -> None:
            if self.read_only:
                self._cancel()
            else:
                self._save()

        @bindings.add("c-q")
        def _cancel(_event) -> None:
            self._cancel()

        @bindings.add("escape")
        def _escape(event) -> None:
            if event.app.layout.has_focus(self.editor):
                event.app.layout.focus(self.tree_window)
                self.status = (
                    "Returned to the Episode tree."
                    if self.read_only
                    else "Returned to the Episode tree; edits remain staged."
                )
                event.app.invalidate()
            else:
                self._cancel()

        return bindings

    def run(self) -> dict[str, Any] | None:
        return self.application.run(handle_sigint=False)


def edit_episode_document(
    document: Mapping[str, Any],
    *,
    missing_value: str,
    changed_paths: tuple[str, ...] = (),
    revision: Optional[int] = None,
    validation_deficits: tuple[Mapping[str, Any], ...] = (),
) -> dict[str, Any] | None:
    """Open the nested editor and return a complete edited working copy."""

    return EpisodeTreeEditor(
        document,
        missing_value=missing_value,
        changed_paths=changed_paths,
        revision=revision,
        validation_deficits=validation_deficits,
    ).run()


def view_episode_document(
    document: Mapping[str, Any],
    *,
    missing_value: str,
    changed_paths: tuple[str, ...] = (),
    revision: Optional[int] = None,
    validation_deficits: tuple[Mapping[str, Any], ...] = (),
) -> None:
    """Open the same nested Episode tree without permitting mutations."""

    EpisodeTreeEditor(
        document,
        missing_value=missing_value,
        read_only=True,
        changed_paths=changed_paths,
        revision=revision,
        validation_deficits=validation_deficits,
    ).run()


__all__ = [
    "EpisodeEditorModel",
    "EpisodeSection",
    "EpisodeTreeEditor",
    "EpisodeTreeEntry",
    "edit_episode_document",
    "view_episode_document",
]
