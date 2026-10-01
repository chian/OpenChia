"""Full-screen Episode Workspace for architecture and built workflow review.

The workspace has two deliberately different surfaces:

* Workflow Architecture is a projection of one persisted Duet artifact.  Its
  declared Episode parts can be edited when the host opens the workspace in
  edit mode.
* Materialized Specification is an immutable projection of one exact
  host-persisted materialization projection, including optional exact code.

Human notes are saved immediately through a host callback and carry the exact
target record supplied by the active view model.  Architecture edits leave the
process only through :class:`EpisodeWorkspaceResult`; this module never writes
host state itself.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import uuid
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Button, Frame, TextArea

from hermes_cli.openchia_episode_views import (
    DEFAULT_MISSING_VALUE,
    MaterializedSpecificationViewModel,
    WorkflowArchitectureViewModel,
    WorkspaceDetail,
    WorkspaceEntry,
    WorkspaceNote,
    WorkspaceTarget,
    notes_from_records,
)


WorkspaceViewModel = Union[
    WorkflowArchitectureViewModel,
    MaterializedSpecificationViewModel,
]
SaveNoteCallback = Callable[
    [Mapping[str, Any], str, str],
    Mapping[str, Any],
]


def _install_modified_tab_sequences() -> None:
    """Map common extended Ctrl-Tab sequences onto PTK's navigation keys.

    A terminal cannot encode Ctrl-Tab in the legacy single-byte key space.
    CSI-u and xterm modifyOtherKeys do encode it, while Control-PageUp/Down are
    the native prompt_toolkit keys used as the portable fallback.
    """

    from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES

    for sequence in ("\x1b[9;5u", "\x1b[27;5;9~"):
        ANSI_SEQUENCES.setdefault(sequence, Keys.ControlPageDown)
    for sequence in ("\x1b[9;6u", "\x1b[27;6;9~"):
        ANSI_SEQUENCES.setdefault(sequence, Keys.ControlPageUp)


@dataclass(frozen=True)
class EpisodeWorkspaceResult:
    """The host-facing result of one workspace session.

    ``architecture_configuration`` is non-``None`` only when the user chose
    Save architecture.  The three ``expected_*`` fields identify the exact
    persisted architecture snapshot on which that proposed replacement was
    based, so the host can perform its own compare-and-swap.  Notes named in
    ``saved_note_ids`` were already persisted by ``save_note`` before the
    workspace returned, even when architecture_configuration is ``None``.
    """

    architecture_configuration: Optional[dict[str, Any]]
    expected_architecture_artifact_id: str
    expected_architecture_content_hash: str
    expected_architecture_revision: int
    saved_note_ids: tuple[str, ...]


class _EpisodeWorkspace:
    _DETAIL_PAGES = ("summary", "declaration", "code", "evidence")

    def __init__(
        self,
        *,
        architecture_snapshot: Mapping[str, Any],
        materialized_snapshot: Optional[Mapping[str, Any]],
        notes: Sequence[Mapping[str, Any]],
        architecture_changed_paths: Sequence[str],
        materialized_changed_paths: Sequence[str],
        edit_architecture: bool,
        architecture_edit_notice: Optional[str],
        save_note: SaveNoteCallback,
        missing_value: str,
    ) -> None:
        if not callable(save_note):
            raise ValueError("save_note must be callable")
        if not isinstance(edit_architecture, bool):
            raise ValueError("edit_architecture must be boolean")
        for name, paths in (
            ("architecture_changed_paths", architecture_changed_paths),
            ("materialized_changed_paths", materialized_changed_paths),
        ):
            if not isinstance(paths, (list, tuple)) or any(
                not isinstance(path, str) for path in paths
            ):
                raise ValueError(f"{name} must be an array of strings")
        if architecture_edit_notice is not None and (
            not isinstance(architecture_edit_notice, str)
            or not architecture_edit_notice.strip()
        ):
            raise ValueError(
                "architecture_edit_notice must be non-empty text or None"
            )

        self.architecture = WorkflowArchitectureViewModel(
            architecture_snapshot,
            changed_paths=tuple(architecture_changed_paths),
            missing_value=missing_value,
        )
        views: list[WorkspaceViewModel] = [self.architecture]
        if materialized_snapshot is not None:
            views.append(
                MaterializedSpecificationViewModel(
                    materialized_snapshot,
                    changed_paths=tuple(materialized_changed_paths),
                )
            )
        self.views = tuple(views)
        self.notes = list(notes_from_records(notes))
        self.save_note_callback = save_note
        self.allow_architecture_edit = (
            edit_architecture and self.architecture.host_editable
        )
        self.saved_note_ids: list[str] = []
        self.active_view_index = 0
        self.selected_keys = {
            view.surface: view.visible_entries()[0].selection_key
            for view in self.views
        }
        self.detail_page_indices = {view.surface: 0 for view in self.views}
        self.detail_positions: dict[
            tuple[str, str, str], tuple[int, int, int]
        ] = {}
        self.note_drafts: dict[str, str] = {}
        self.note_attempts: dict[str, tuple[str, str]] = {}
        self.note_cursors: dict[str, int] = {}
        self._detail_editable = False
        self._loaded_detail_text = ""
        if architecture_edit_notice is not None:
            self._status = architecture_edit_notice
        elif self.allow_architecture_edit:
            self._status = "Architecture editing is available."
        elif edit_architecture:
            self._status = (
                "The architecture snapshot is host-frozen; browsing and notes are available."
            )
        else:
            self._status = "Browsing and notes are available."
        self._status_is_error = False

        self.view_tabs_control = FormattedTextControl(
            self._view_tabs_fragments,
            focusable=True,
        )
        self.view_tabs_window = Window(
            self.view_tabs_control,
            height=1,
            dont_extend_height=True,
        )
        self.tree_control = FormattedTextControl(
            self._tree_fragments,
            focusable=True,
            get_cursor_position=self._tree_cursor_position,
        )
        self.tree_window = Window(
            self.tree_control,
            width=Dimension(min=30, preferred=42, max=58),
            wrap_lines=False,
            right_margins=[ScrollbarMargin(display_arrows=True)],
        )
        self.detail_heading_control = FormattedTextControl(
            self._detail_heading_fragments
        )
        self.detail_heading_window = Window(
            self.detail_heading_control,
            height=2,
            wrap_lines=True,
            dont_extend_height=True,
        )
        self.detail_tabs_control = FormattedTextControl(
            self._detail_tabs_fragments,
            focusable=True,
        )
        self.detail_tabs_window = Window(
            self.detail_tabs_control,
            height=1,
            dont_extend_height=True,
        )
        self.detail_area = TextArea(
            multiline=True,
            scrollbar=True,
            wrap_lines=False,
            read_only=Condition(lambda: not self._detail_editable),
        )
        self.notes_control = FormattedTextControl(
            self._notes_fragments,
            focusable=True,
            get_cursor_position=self._notes_cursor_position,
        )
        self.notes_window = Window(
            self.notes_control,
            height=Dimension(min=3, preferred=6, max=9),
            wrap_lines=True,
            right_margins=[ScrollbarMargin(display_arrows=True)],
        )
        self.note_input = TextArea(
            height=4,
            multiline=True,
            wrap_lines=True,
            prompt="Note> ",
            read_only=Condition(lambda: self._detail().target is None),
        )
        self.status_control = FormattedTextControl(self._status_fragments)
        self.status_window = Window(
            self.status_control,
            height=2,
            wrap_lines=True,
            dont_extend_height=True,
        )

        self.save_note_button = Button("Save note", handler=self._save_note)
        self.save_architecture_button: Optional[Button] = None
        if self.allow_architecture_edit:
            self.save_architecture_button = Button(
                "Save architecture",
                handler=self._submit_architecture,
            )
        self.close_button = Button("Close", handler=self._close)

        button_items: list[Any] = [self.save_note_button]
        if self.save_architecture_button is not None:
            button_items.append(self.save_architecture_button)
        button_items.append(self.close_button)

        right_column = HSplit(
            [
                self.detail_heading_window,
                self.detail_tabs_window,
                Frame(self.detail_area, title="Selected part"),
                Frame(self.notes_window, title="Target notes"),
                Frame(self.note_input, title="New target note"),
            ]
        )
        body = VSplit(
            [
                Frame(self.tree_window, title="Workflow parts"),
                right_column,
            ],
            padding=1,
        )
        buttons = VSplit(button_items, padding=1)
        root = HSplit(
            [
                Frame(self.view_tabs_window, title="Episode Workspace"),
                body,
                buttons,
                self.status_window,
            ]
        )

        self.bindings = self._build_bindings()
        self.application: Application[EpisodeWorkspaceResult] = Application(
            layout=Layout(root, focused_element=self.tree_window),
            key_bindings=self.bindings,
            style=self._style(),
            full_screen=True,
            mouse_support=True,
        )
        self._load_detail()
        self._load_note_draft()

    @property
    def active_view(self) -> WorkspaceViewModel:
        return self.views[self.active_view_index]

    @property
    def selected_index(self) -> int:
        entries = self.active_view.visible_entries()
        selected = self.selected_keys[self.active_view.surface]
        return next(
            (
                index
                for index, entry in enumerate(entries)
                if entry.selection_key == selected
            ),
            0,
        )

    @selected_index.setter
    def selected_index(self, value: int) -> None:
        entries = self.active_view.visible_entries()
        maximum = max(0, len(entries) - 1)
        selected = min(max(0, value), maximum)
        self.selected_keys[self.active_view.surface] = entries[selected].selection_key

    @property
    def active_detail_page_index(self) -> int:
        return self.detail_page_indices[self.active_view.surface]

    @active_detail_page_index.setter
    def active_detail_page_index(self, value: int) -> None:
        self.detail_page_indices[self.active_view.surface] = value

    def _entries(self) -> list[WorkspaceEntry]:
        return self.active_view.visible_entries()

    def _entry(self) -> WorkspaceEntry:
        entries = self._entries()
        if not entries:
            raise ValueError("the active workspace view has no projected parts")
        return entries[self.selected_index]

    def _detail(self) -> WorkspaceDetail:
        return self.active_view.detail_for(self._entry())

    def _active_page(self) -> str:
        return self._DETAIL_PAGES[self.active_detail_page_index]

    def _can_edit_detail(self, detail: WorkspaceDetail) -> bool:
        return (
            self.allow_architecture_edit
            and self.active_view is self.architecture
            and self._active_page() == "declaration"
            and detail.editable
        )

    def _detail_position_key(
        self,
        detail: Optional[WorkspaceDetail] = None,
        page: Optional[str] = None,
    ) -> tuple[str, str, str]:
        current = self._detail() if detail is None else detail
        return (
            self.active_view.surface,
            self._detail_state_id(current),
            self._active_page() if page is None else page,
        )

    def _detail_state_id(
        self,
        detail: Optional[WorkspaceDetail] = None,
    ) -> str:
        current = self._detail() if detail is None else detail
        if current.target is not None:
            return current.target.target_id
        return "unaddressed:" + ":".join(self._entry().selection_key)

    def _remember_detail_position(
        self,
        detail: Optional[WorkspaceDetail] = None,
    ) -> None:
        if not hasattr(self, "detail_area"):
            return
        self.detail_positions[self._detail_position_key(detail)] = (
            self.detail_area.buffer.cursor_position,
            int(self.detail_area.window.vertical_scroll or 0),
            int(self.detail_area.window.horizontal_scroll or 0),
        )

    def _remember_note_draft(
        self,
        target: Optional[WorkspaceTarget],
    ) -> None:
        if not hasattr(self, "note_input"):
            return
        if target is not None:
            self.note_drafts[target.target_id] = self.note_input.text

    def _load_note_draft(self) -> None:
        target = self._detail().target
        text = "" if target is None else self.note_drafts.get(target.target_id, "")
        self.note_input.buffer.set_document(
            Document(text=text, cursor_position=len(text)),
            bypass_readonly=True,
        )

    def _remember_current_target_state(self) -> None:
        detail = self._detail()
        self._remember_detail_position(detail)
        self._remember_note_draft(detail.target)

    def _load_detail(self) -> None:
        detail = self._detail()
        self._detail_editable = self._can_edit_detail(detail)
        text = detail.page(self._active_page())
        self._loaded_detail_text = text
        self.detail_area.buffer.set_document(
            Document(text=text, cursor_position=0),
            bypass_readonly=True,
        )
        cursor, vertical, horizontal = self.detail_positions.get(
            self._detail_position_key(detail),
            (0, 0, 0),
        )
        self.detail_area.buffer.cursor_position = min(cursor, len(text))
        self.detail_area.window.vertical_scroll = max(0, vertical)
        self.detail_area.window.horizontal_scroll = max(0, horizontal)
        self._invalidate()

    def _invalidate(self) -> None:
        application = getattr(self, "application", None)
        if application is not None:
            application.invalidate()

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self._status = message
        self._status_is_error = error
        self._invalidate()

    def _restore_selection(
        self,
        selection_key: tuple[str, str, str],
    ) -> None:
        entries = self._entries()
        for index, entry in enumerate(entries):
            if entry.selection_key == selection_key:
                self.selected_index = index
                return
        _kind, local_id, _part_key = selection_key
        if local_id:
            self.selected_index = self.active_view.index_for_episode(local_id)
        else:
            self.selected_index = 0

    def _commit_detail_edit(self) -> bool:
        if not self._detail_editable:
            return True
        if self.detail_area.text == self._loaded_detail_text:
            return True
        entry = self._entry()
        if entry.part is None or entry.episode is None:
            return True
        old_detail = self._detail()
        old_position_key = self._detail_position_key(old_detail)
        self._remember_detail_position(old_detail)
        self._remember_note_draft(old_detail.target)
        try:
            payload = json.loads(self.detail_area.text)
        except json.JSONDecodeError as exc:
            self._set_status(
                f"Declaration JSON is invalid at line {exc.lineno}, column {exc.colno}: {exc.msg}",
                error=True,
            )
            return False
        selection_key = entry.selection_key
        local_id = entry.episode.local_id
        part_key = entry.part.key
        part_label = entry.part.label
        try:
            self.architecture.apply_part(local_id, part_key, payload)
        except (TypeError, ValueError) as exc:
            self._set_status(f"Architecture edit was not applied: {exc}", error=True)
            return False
        self._restore_selection(selection_key)
        new_detail = self._detail()
        old_position = self.detail_positions.get(old_position_key)
        if old_position is not None:
            self.detail_positions[self._detail_position_key(new_detail)] = old_position
        self._load_detail()
        self._load_note_draft()
        self._set_status(
            f"Staged {local_id} / {part_label}; Save architecture submits the complete document."
        )
        return True

    def _select_tree_index(self, index: int) -> bool:
        if not self._commit_detail_edit():
            return False
        self._remember_current_target_state()
        self.selected_index = index
        self._load_detail()
        self._load_note_draft()
        return True

    def _activate_view(self, index: int) -> bool:
        if index == self.active_view_index:
            return True
        if index < 0 or index >= len(self.views):
            return False
        if not self._commit_detail_edit():
            return False
        self._remember_current_target_state()
        self.active_view_index = index
        self._load_detail()
        self._load_note_draft()
        self._set_status(f"Viewing {self.active_view.title}.")
        return True

    def _activate_detail_page(self, index: int) -> bool:
        if index == self.active_detail_page_index:
            return True
        if index < 0 or index >= len(self._DETAIL_PAGES):
            return False
        if not self._commit_detail_edit():
            return False
        self._remember_current_target_state()
        self.active_detail_page_index = index
        self._load_detail()
        self._load_note_draft()
        return True

    def _toggle_selected_episode(self, expanded: Optional[bool] = None) -> None:
        if not self._commit_detail_edit():
            return
        entry = self._entry()
        if entry.episode is None or entry.part is not None:
            get_app().layout.focus(self.detail_tabs_window)
            return
        self._remember_current_target_state()
        local_id = entry.episode.local_id
        self.active_view.toggle(entry.episode, expanded=expanded)
        self._restore_selection(("episode", local_id, ""))
        self._load_detail()
        self._load_note_draft()

    def _collapse_or_parent(self) -> None:
        entry = self._entry()
        if entry.episode is None:
            get_app().layout.focus(self.detail_tabs_window)
            return
        if entry.part is not None:
            self._select_tree_index(
                self.active_view.index_for_episode(entry.episode.local_id)
            )
            return
        if entry.episode.local_id in self.active_view.expanded_episode_ids:
            self._toggle_selected_episode(expanded=False)
            return
        parent_id = entry.episode.parent_local_id
        if parent_id is not None:
            self._select_tree_index(self.active_view.index_for_episode(parent_id))

    def _expand_or_detail(self) -> None:
        entry = self._entry()
        if entry.episode is not None and entry.part is None:
            self._toggle_selected_episode(expanded=True)
        else:
            get_app().layout.focus(self.detail_tabs_window)

    def _notes_for_target(
        self,
        target: Optional[WorkspaceTarget],
    ) -> list[tuple[str, WorkspaceNote]]:
        if target is None:
            return []
        return [
            ("this target", note)
            for note in self.notes
            if note.target.target_id == target.target_id
        ]

    def _notes_line_count(
        self,
        target: Optional[WorkspaceTarget],
    ) -> int:
        current = target
        notes = self._notes_for_target(current)
        if not notes:
            return 1
        return sum(
            1 + max(1, note.body.count("\n") + 1)
            for _scope, note in notes
        ) + max(0, len(notes) - 1) * 2

    def _notes_cursor_position(self) -> Point:
        target = self._detail().target
        maximum = max(0, self._notes_line_count(target) - 1)
        target_id = self._detail_state_id()
        cursor = min(max(0, self.note_cursors.get(target_id, 0)), maximum)
        self.note_cursors[target_id] = cursor
        return Point(x=0, y=cursor)

    def _scroll_notes(self, delta: int) -> None:
        target = self._detail().target
        maximum = max(0, self._notes_line_count(target) - 1)
        target_id = self._detail_state_id()
        current = self.note_cursors.get(target_id, 0)
        self.note_cursors[target_id] = min(
            max(0, current + delta),
            maximum,
        )
        self._invalidate()

    def _save_note(self) -> None:
        if not self._commit_detail_edit():
            return
        target = self._detail().target
        if target is None:
            self._set_status(
                "Choose a persisted workflow or materialized part before adding a note.",
                error=True,
            )
            return
        body = self.note_input.text.strip()
        if not body:
            self._set_status("Enter a note before saving it.", error=True)
            return
        self.note_drafts[target.target_id] = self.note_input.text
        if self.active_view is self.architecture and self.architecture.dirty:
            self._set_status(
                "Save architecture first, then attach this note to its persisted revision.",
                error=True,
            )
            return
        prior_attempt = self.note_attempts.get(target.target_id)
        if prior_attempt is not None and prior_attempt[0] == body:
            idempotency_key = prior_attempt[1]
        else:
            idempotency_key = f"workspace_note_{uuid.uuid4().hex}"
            self.note_attempts[target.target_id] = (body, idempotency_key)
        try:
            persisted = self.save_note_callback(
                target.as_record(),
                body,
                idempotency_key,
            )
            note = WorkspaceNote.from_record(persisted)
            if note.target.target_id != target.target_id:
                raise ValueError("the saved note returned a different target")
            if note.body != body:
                raise ValueError("the saved note returned different prose")
            existing = next(
                (
                    item
                    for item in self.notes
                    if item.note_id == note.note_id
                ),
                None,
            )
            if existing is not None and existing.as_record() != note.as_record():
                raise ValueError("the saved note ID names different content")
        except Exception as exc:
            self._set_status(f"Note was not saved: {exc}", error=True)
            return
        if existing is None:
            self.notes.append(note)
        if note.note_id not in self.saved_note_ids:
            self.saved_note_ids.append(note.note_id)
        self.note_drafts.pop(target.target_id, None)
        self.note_attempts.pop(target.target_id, None)
        self.note_input.buffer.set_document(
            Document(text="", cursor_position=0),
            bypass_readonly=True,
        )
        self.note_cursors[target.target_id] = max(
            0,
            self._notes_line_count(target) - 1,
        )
        location = target.json_pointer or "the workflow root"
        self._set_status(f"Saved note {note.note_id} for {location}.")

    def _result(
        self,
        architecture_configuration: Optional[dict[str, Any]],
    ) -> EpisodeWorkspaceResult:
        return EpisodeWorkspaceResult(
            architecture_configuration=architecture_configuration,
            expected_architecture_artifact_id=self.architecture.source_artifact_id,
            expected_architecture_content_hash=self.architecture.content_hash,
            expected_architecture_revision=self.architecture.revision,
            saved_note_ids=tuple(self.saved_note_ids),
        )

    def _submit_architecture(self) -> None:
        if not self.allow_architecture_edit:
            self._set_status("This architecture snapshot is read-only.", error=True)
            return
        if not self._commit_detail_edit():
            return
        self.application.exit(result=self._result(self.architecture.result()))

    def _close(self) -> None:
        self.application.exit(result=self._result(None))

    def _view_tabs_fragments(self) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        for index, view in enumerate(self.views):
            active = index == self.active_view_index
            mode = " · edit" if view is self.architecture and self.allow_architecture_edit else ""
            text = f" {index + 1} {view.title}{mode} "

            def click(
                mouse_event: MouseEvent,
                tab_index: int = index,
            ) -> None:
                if mouse_event.event_type == MouseEventType.MOUSE_UP:
                    if self._activate_view(tab_index):
                        get_app().layout.focus(self.view_tabs_window)

            fragments.append(
                (
                    "class:view-tab.active" if active else "class:view-tab",
                    text,
                    click,
                )
            )
            fragments.append(("", " "))
        return fragments

    def _tree_fragments(self) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        entries = self._entries()
        self.selected_index = self.selected_index
        for index, entry in enumerate(entries):
            selected = index == self.selected_index
            if entry.kind == "global" and entry.part is not None:
                flags = ""
                if entry.part.changed:
                    flags += " Δ"
                if entry.part.incomplete:
                    flags += " ?"
                label = f"◆ {entry.part.label}{flags}"
                style = "class:tree.global"
            elif entry.part is None and entry.episode is not None:
                expanded = entry.episode.local_id in self.active_view.expanded_episode_ids
                marker = "▾" if expanded else "▸"
                changed = " Δ" if entry.episode.changed else ""
                label = f"{marker} {entry.episode.name}{changed}"
                style = "class:tree.episode"
            elif entry.part is not None:
                flags = ""
                if entry.part.changed:
                    flags += " Δ"
                if entry.part.incomplete:
                    flags += " ?"
                if (
                    entry.part.editable
                    and self.active_view is self.architecture
                    and self.allow_architecture_edit
                ):
                    flags += " ✎"
                label = f"· {entry.part.label}{flags}"
                style = "class:tree.part"
            else:
                raise ValueError("workspace tree entry is malformed")
            text = f"{'  ' * entry.depth}{label}"

            def click(
                mouse_event: MouseEvent,
                row_index: int = index,
            ) -> None:
                if mouse_event.event_type == MouseEventType.MOUSE_UP:
                    if self._select_tree_index(row_index):
                        get_app().layout.focus(self.tree_window)

            if selected:
                style += ".selected"
            fragments.append((style, text, click))
            if index < len(entries) - 1:
                fragments.append(("", "\n"))
        return fragments

    def _tree_cursor_position(self) -> Point:
        return Point(x=0, y=self.selected_index)

    def _detail_heading_fragments(self) -> StyleAndTextTuples:
        detail = self._detail()
        mode = "editable declaration" if self._detail_editable else "read-only"
        return [
            ("class:detail.heading", f"{detail.heading}  [{mode}]\n"),
            ("class:detail.description", detail.description),
        ]

    def _detail_tabs_fragments(self) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        for index, page in enumerate(self._DETAIL_PAGES):
            active = index == self.active_detail_page_index

            def click(
                mouse_event: MouseEvent,
                page_index: int = index,
            ) -> None:
                if mouse_event.event_type == MouseEventType.MOUSE_UP:
                    if self._activate_detail_page(page_index):
                        get_app().layout.focus(self.detail_tabs_window)

            fragments.append(
                (
                    "class:detail-tab.active" if active else "class:detail-tab",
                    f" {page.title()} ",
                    click,
                )
            )
            fragments.append(("", " "))
        return fragments

    def _notes_fragments(self) -> StyleAndTextTuples:
        target = self._detail().target
        notes = self._notes_for_target(target)
        if target is None:
            return [
                (
                    "class:notes.empty",
                    "This display-only part has no persisted note target.",
                )
            ]
        if not notes:
            return [("class:notes.empty", "No saved notes for this target.")]
        fragments: StyleAndTextTuples = []
        for index, (scope, note) in enumerate(notes):
            fragments.extend(
                [
                    ("class:notes.id", f"{note.note_id} [{scope}]"),
                    ("", "\n"),
                    ("class:notes.body", note.body),
                ]
            )
            if index < len(notes) - 1:
                fragments.append(("", "\n\n"))
        return fragments

    def _status_fragments(self) -> StyleAndTextTuples:
        architecture_help = (
            " · Ctrl-S save architecture" if self.allow_architecture_edit else ""
        )
        return [
            (
                "class:status.error" if self._status_is_error else "class:status",
                self._status,
            ),
            (
                "class:help",
                "\nCtrl-Tab/Shift-Ctrl-Tab view · Tab/Shift-Tab pane · "
                "arrows navigate · Enter open · "
                f"Ctrl-N save note{architecture_help} · Esc back/close",
            ),
        ]

    def _focusables(self) -> list[Any]:
        items: list[Any] = [
            self.view_tabs_window,
            self.tree_window,
            self.detail_tabs_window,
            self.detail_area,
            self.notes_window,
            self.note_input,
            self.save_note_button,
        ]
        if self.save_architecture_button is not None:
            items.append(self.save_architecture_button)
        items.append(self.close_button)
        return items

    def _cycle_focus(self, delta: int) -> None:
        layout = get_app().layout
        focusables = self._focusables()
        current = next(
            (index for index, item in enumerate(focusables) if layout.has_focus(item)),
            0,
        )
        if layout.has_focus(self.detail_area) and not self._commit_detail_edit():
            return
        self._remember_current_target_state()
        layout.focus(focusables[(current + delta) % len(focusables)])

    def _escape(self) -> None:
        layout = get_app().layout
        if layout.has_focus(self.tree_window):
            self._close()
            return
        if layout.has_focus(self.detail_area) and not self._commit_detail_edit():
            return
        self._remember_current_target_state()
        layout.focus(self.tree_window)
        self._set_status("Workflow parts focused; press Esc again to close.")

    def _build_bindings(self) -> KeyBindings:
        _install_modified_tab_sequences()
        bindings = KeyBindings()

        @bindings.add("tab", eager=True)
        def _next_focus(event: Any) -> None:
            self._cycle_focus(1)

        @bindings.add(Keys.BackTab, eager=True)
        def _previous_focus(event: Any) -> None:
            self._cycle_focus(-1)

        @bindings.add("escape", eager=True)
        def _escape(event: Any) -> None:
            self._escape()

        @bindings.add("c-n", eager=True)
        def _save_note(event: Any) -> None:
            self._save_note()

        @bindings.add("c-s", eager=True)
        def _save_architecture(event: Any) -> None:
            self._submit_architecture()

        @bindings.add(Keys.ControlPageDown, eager=True)
        def _next_workspace_view(event: Any) -> None:
            self._activate_view((self.active_view_index + 1) % len(self.views))

        @bindings.add(Keys.ControlPageUp, eager=True)
        def _previous_workspace_view(event: Any) -> None:
            self._activate_view((self.active_view_index - 1) % len(self.views))

        @bindings.add("left", filter=has_focus(self.view_tabs_window))
        def _previous_view(event: Any) -> None:
            self._activate_view((self.active_view_index - 1) % len(self.views))

        @bindings.add("right", filter=has_focus(self.view_tabs_window))
        def _next_view(event: Any) -> None:
            self._activate_view((self.active_view_index + 1) % len(self.views))

        @bindings.add("enter", filter=has_focus(self.view_tabs_window))
        def _enter_view(event: Any) -> None:
            get_app().layout.focus(self.tree_window)

        @bindings.add("up", filter=has_focus(self.tree_window))
        def _tree_up(event: Any) -> None:
            self._select_tree_index(self.selected_index - 1)

        @bindings.add("down", filter=has_focus(self.tree_window))
        def _tree_down(event: Any) -> None:
            self._select_tree_index(self.selected_index + 1)

        @bindings.add("left", filter=has_focus(self.tree_window))
        def _tree_left(event: Any) -> None:
            self._collapse_or_parent()

        @bindings.add("right", filter=has_focus(self.tree_window))
        def _tree_right(event: Any) -> None:
            self._expand_or_detail()

        @bindings.add("enter", filter=has_focus(self.tree_window))
        def _tree_enter(event: Any) -> None:
            self._toggle_selected_episode()

        @bindings.add("left", filter=has_focus(self.detail_tabs_window))
        def _previous_detail_page(event: Any) -> None:
            self._activate_detail_page(
                (self.active_detail_page_index - 1) % len(self._DETAIL_PAGES)
            )

        @bindings.add("right", filter=has_focus(self.detail_tabs_window))
        def _next_detail_page(event: Any) -> None:
            self._activate_detail_page(
                (self.active_detail_page_index + 1) % len(self._DETAIL_PAGES)
            )

        @bindings.add("enter", filter=has_focus(self.detail_tabs_window))
        def _enter_detail_page(event: Any) -> None:
            get_app().layout.focus(self.detail_area)

        @bindings.add("up", filter=has_focus(self.notes_window))
        def _notes_up(event: Any) -> None:
            self._scroll_notes(-1)

        @bindings.add("down", filter=has_focus(self.notes_window))
        def _notes_down(event: Any) -> None:
            self._scroll_notes(1)

        @bindings.add("pageup", filter=has_focus(self.notes_window))
        def _notes_page_up(event: Any) -> None:
            self._scroll_notes(-5)

        @bindings.add("pagedown", filter=has_focus(self.notes_window))
        def _notes_page_down(event: Any) -> None:
            self._scroll_notes(5)

        @bindings.add("left", filter=has_focus(self.notes_window))
        def _notes_back(event: Any) -> None:
            get_app().layout.focus(self.tree_window)

        @bindings.add("right", filter=has_focus(self.notes_window))
        @bindings.add("enter", filter=has_focus(self.notes_window))
        def _notes_to_input(event: Any) -> None:
            get_app().layout.focus(self.note_input)

        for index in range(min(9, len(self.views))):

            def activate_view(event: Any, view_index: int = index) -> None:
                self._activate_view(view_index)

            bindings.add(str(index + 1), filter=has_focus(self.view_tabs_window))(
                activate_view
            )

        return bindings

    @staticmethod
    def _style() -> Style:
        return Style.from_dict(
            {
                "frame.label": "bold #7aa2f7",
                "view-tab": "#9aa5ce",
                "view-tab.active": "bold #1a1b26 bg:#7aa2f7",
                "tree.episode": "bold #c0caf5",
                "tree.episode.selected": "bold #1a1b26 bg:#7dcfff",
                "tree.global": "bold #e0af68",
                "tree.global.selected": "bold #1a1b26 bg:#e0af68",
                "tree.part": "#a9b1d6",
                "tree.part.selected": "#1a1b26 bg:#bb9af7",
                "detail.heading": "bold #c0caf5",
                "detail.description": "#9aa5ce",
                "detail-tab": "#9aa5ce",
                "detail-tab.active": "bold #1a1b26 bg:#9ece6a",
                "notes.empty": "italic #565f89",
                "notes.id": "bold #e0af68",
                "notes.body": "#c0caf5",
                "status": "#9ece6a",
                "status.error": "bold #f7768e",
                "help": "#565f89",
                "button": "#c0caf5 bg:#3b4261",
                "button.focused": "bold #1a1b26 bg:#7aa2f7",
                "text-area": "#c0caf5 bg:#1f2335",
            }
        )

    def run(self) -> EpisodeWorkspaceResult:
        return self.application.run()


def open_episode_workspace(
    *,
    architecture_snapshot: Mapping[str, Any],
    materialized_snapshot: Optional[Mapping[str, Any]],
    notes: Sequence[Mapping[str, Any]],
    save_note: SaveNoteCallback,
    architecture_changed_paths: Sequence[str] = (),
    materialized_changed_paths: Sequence[str] = (),
    edit_architecture: bool = False,
    architecture_edit_notice: Optional[str] = None,
    missing_value: str = DEFAULT_MISSING_VALUE,
) -> EpisodeWorkspaceResult:
    """Open one workspace over exact host-provided persisted snapshots.

    ``save_note`` is called synchronously as
    ``save_note(target_record, body, idempotency_key)``.  One key is retained
    across retries of the same exact target/body pair.  The callback must
    durably persist the note and return the complete strict note record
    accepted by :meth:`WorkspaceNote.from_record`.  Architecture replacement
    remains a separate host operation performed after this function returns.
    """

    workspace = _EpisodeWorkspace(
        architecture_snapshot=architecture_snapshot,
        materialized_snapshot=materialized_snapshot,
        notes=notes,
        architecture_changed_paths=architecture_changed_paths,
        materialized_changed_paths=materialized_changed_paths,
        edit_architecture=edit_architecture,
        architecture_edit_notice=architecture_edit_notice,
        save_note=save_note,
        missing_value=missing_value,
    )
    return workspace.run()


__all__ = [
    "EpisodeWorkspaceResult",
    "SaveNoteCallback",
    "open_episode_workspace",
]
