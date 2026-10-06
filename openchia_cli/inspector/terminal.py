"""Shared terminal shell; domain providers own records and historical cursors."""

import asyncio
from copy import copy
import shlex

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.data_structures import Point
from prompt_toolkit.widgets import TextArea, Frame
from prompt_toolkit.styles import Style

from .model import Detail, Link, display_text
from .navigation import Navigation
from .render import detail_text


class InspectorTerminal:
    def __init__(self, controller, *, input=None, output=None):
        self.controller = controller
        self.navigation = Navigation()
        self.navigation.active_only = True
        self.view = None
        self.detail = None
        self.page = 0
        self.link_index = 0
        self.back_stack = []
        self.detail_visible = True
        self.scroll_positions = {}
        self.status = 'Loading recorded state…'
        self.loading = False
        self.refresh_pending = False
        self.generation = 0
        self.tree = FormattedTextControl(self.tree_fragments, focusable=True,
                                         get_cursor_position=self.tree_cursor)
        self.tree_window = Window(self.tree, wrap_lines=False, width=Dimension(min=25, preferred=55, weight=1))
        self.details = TextArea(read_only=True, scrollbar=True, wrap_lines=True)
        self.links = FormattedTextControl(self.link_fragments, focusable=True,
                                          get_cursor_position=lambda: Point(0, self.link_index))
        self.links_window = Window(self.links, height=Dimension(min=2, max=6), wrap_lines=False)
        self.command = TextArea(height=1, prompt=': ', multiline=False, accept_handler=self.accept_command)
        from prompt_toolkit.layout.containers import ConditionalContainer
        root = HSplit([
            Window(FormattedTextControl(self.header), height=3),
            VSplit([Frame(self.tree_window, title='Work tree'),
                    ConditionalContainer(Frame(HSplit([
                        Window(FormattedTextControl(self.detail_header), height=2), self.details,
                        Frame(self.links_window, title='References · Enter to open'),
                    ]), title='Details', width=Dimension(min=25, preferred=55, weight=1)), filter=Condition(lambda: self.detail_visible))]),
            Window(FormattedTextControl(lambda: display_text(self.status)), height=1),
            Window(FormattedTextControl('↑↓ select  ←→ fold  Enter details  Tab pane  z focus  u parent\n'
                                       '[ ] history  l live  f follow  a all branches  : commands  Esc close'), height=2),
            self.command,
        ])
        self.application = Application(layout=Layout(root, focused_element=self.tree_window),
            key_bindings=self.bindings(), full_screen=True, input=input, output=output,
            style=Style.from_dict({'selected': 'reverse', 'active': 'ansigreen bold',
                                   'waiting': 'ansiyellow', 'superseded': 'ansibrightblack'}))

    def header(self):
        if not self.view:
            return self.status
        snapshot = self.view.snapshot
        pos = snapshot.position
        cursor = f'step {pos["step"]}/{pos["latest_step"]}'
        if pos.get('run_id'):
            cursor += f' · Run …{pos["run_id"][-12:]} · event {pos["run_event"]}'
        recorded = f'Recorded {pos["time"][:19]}Z'
        if pos.get('selected_time'):
            recorded += f' · selected {pos["selected_time"]}'
        return display_text(f'{snapshot.title} · {pos["mode"].upper()} · {cursor} · Follow {"on" if self.navigation.follow else "off"}\n'
                            f'Campaign …{snapshot.identity[-12:]} · Duet …{pos["duet_id"][-12:]} · {"Active branches" if self.navigation.active_only else "All branches"}\n'
                            f'{recorded} · refreshed {pos["observed_at"][11:19]}Z')

    def tree_fragments(self):
        fragments = []
        for node, depth in self.navigation.visible():
            mark = '−' if node.identity in self.navigation.expanded else '+'
            style = 'class:selected' if node.identity == self.navigation.selected else f'class:{node.status}'
            line = f'{"  " * depth}{mark} {node.label} [{node.status}] · {node.counters.get("completed_iterations", 0)} iterations'
            goal = f'{"  " * depth}  {" ".join(node.summary.split())}'
            fragments.append((style, display_text(line) + '\n' + display_text(goal) + '\n'))
        return fragments

    def tree_cursor(self):
        rows = [n.identity for n, _ in self.navigation.visible()]
        return Point(0, rows.index(self.navigation.selected) * 2 if self.navigation.selected in rows else 0)

    def detail_header(self):
        if not self.detail:
            return 'Select an assignment'
        pages = list(self.detail.sections)
        return display_text(f'{self.detail.domain} · {self.detail.title[:100]}\n'
                            f'{pages[self.page]} · n/p section · Space show/hide details')

    def link_fragments(self):
        return [('class:selected' if i == self.link_index else '',
                 display_text(f'{link.label}: {link.identity}') + '\n')
                for i, link in enumerate(self.detail.links if self.detail else [])]

    def remember_scroll(self):
        if self.detail:
            key = (self.detail.domain, self.detail.identity, list(self.detail.sections)[self.page])
            self.scroll_positions[key] = (self.details.buffer.cursor_position, self.details.window.vertical_scroll)

    def install_detail(self, detail, *, remember=True):
        if remember:
            self.remember_scroll()
        same = self.detail and (self.detail.domain, self.detail.identity) == (detail.domain, detail.identity)
        self.detail = detail
        self.page = min(self.page, len(detail.sections) - 1) if same else 0
        self.link_index = min(self.link_index, max(0, len(detail.links) - 1)) if same else 0
        self.draw_detail()

    def draw_detail(self):
        if not self.detail:
            return
        page = list(self.detail.sections)[self.page]
        self.details.text = detail_text(self.detail, page)
        cursor, scroll = self.scroll_positions.get((self.detail.domain, self.detail.identity, page), (0, 0))
        self.details.buffer.cursor_position = min(cursor, len(self.details.text))
        self.details.window.vertical_scroll = scroll
        if self.detail.gaps:
            self.status = ' | '.join(self.detail.gaps)
        self.application.invalidate()

    def clear_detail(self):
        self.remember_scroll()
        self.detail = None
        self.details.text = ''
        self.page = self.link_index = 0

    async def refresh(self):
        if self.back_stack:
            return
        if self.loading:
            self.refresh_pending = True
            return
        self.loading = True
        self.generation += 1
        try:
            view = await asyncio.to_thread(self.controller.capture)
            navigation = copy(self.navigation)
            navigation.expanded = self.navigation.expanded.copy()
            navigation.update(view.snapshot)
            identity = navigation.selected
            detail = None
            if identity:
                detail = await asyncio.to_thread(view.detail, identity)
            elif view.run:
                detail = await asyncio.to_thread(view.reference, 'run', view.run[0]['run_id'])
            # Opening a reference freezes its observation context, including
            # when a scheduled refresh was already reading in the background.
            if self.back_stack or self.refresh_pending:
                return
            self.view = view
            self.navigation.update(view.snapshot)
            self.status = ' | '.join(view.snapshot.gaps) or 'Recorded states; returned does not imply accepted.'
            if detail and self.navigation.selected == identity:
                self.install_detail(detail)
            else:
                self.clear_detail()
                if self.navigation.selected:
                    self.task(self.selected_detail())
        except (ValueError, OSError) as exc:
            self.status = f'Observation unavailable; last display retained: {exc}'
        finally:
            self.loading = False
            self.application.invalidate()
            if self.refresh_pending:
                self.refresh_pending = False
                self.task(self.refresh())

    async def watch(self):
        await self.refresh()
        while True:
            await asyncio.sleep(3)
            if self.controller.live and not self.back_stack:
                await self.refresh()

    async def selected_detail(self):
        if not self.view or not self.navigation.selected:
            return
        self.back_stack.clear()
        view, identity, generation = self.view, self.navigation.selected, self.generation
        try:
            detail = await asyncio.to_thread(view.detail, identity)
            if generation == self.generation and identity == self.navigation.selected:
                self.install_detail(detail)
        except (ValueError, OSError) as exc:
            self.status = str(exc)

    async def open_link(self):
        if not self.detail or not self.detail.links:
            return
        link = self.detail.links[self.link_index]
        view, generation = self.view, self.generation
        try:
            detail = await asyncio.to_thread(view.reference, link.domain, link.identity)
            if generation != self.generation or view is not self.view:
                return
            self.back_stack.append(self.detail)
            self.navigation.follow = False
            self.install_detail(detail)
            self.application.layout.focus(self.details)
        except (ValueError, OSError) as exc:
            self.status = str(exc)

    def task(self, coro):
        self.application.create_background_task(coro)

    def accept_command(self, buffer):
        command = buffer.text
        buffer.text = ''
        self.task(self.execute(command))
        return True

    async def execute(self, command):
        try:
            parts = shlex.split(command)
            if not parts:
                return
            action, args = parts[0], parts[1:]
            handlers = {'campaigns': self.show_campaigns, 'runs': self.show_runs,
                        'help': self.show_help, 'node': self.select_node}
            if action in handlers:
                await handlers[action](args)
            else:
                self.controller.command(action, args)
                self.back_stack.clear()
                await self.refresh()
        except (ValueError, OSError) as exc:
            self.status = str(exc)
        self.application.layout.focus(self.tree_window)
        self.application.invalidate()

    async def show_campaigns(self, args):
        rows = await asyncio.to_thread(self.controller.campaigns)
        self.open_panel(Detail('campaigns', 'catalog', 'Recorded campaigns', {'campaigns': rows},
            [Link('Select with :campaign', 'campaign', row['campaign_id']) for row in rows]))

    async def show_runs(self, args):
        links = await asyncio.to_thread(self.view.run_links)
        self.open_panel(Detail('runs', 'catalog', 'Recorded Refiner Runs',
                                  {'runs': [link.identity for link in links]}, links))

    async def show_help(self, args):
        self.open_panel(Detail('help', 'help', 'Inspector commands', {'commands': [
            ':campaigns / :campaign ID — choose recorded campaign', ':runs / :run ID — choose Run',
            ':at STEP / :time ISO_TIMESTAMP — campaign history', ':event NUMBER — selected Run history',
            ':live — return to current campaign', ':node ID — select an invocation',
            '[ / ] — previous/next campaign step or selected Run event',
            'h — hold current position in history; l — live; f — follow active assignment',
            'z — focus subtree; u — enclosing subtree; Space — toggle details',
            'a — show all branches, including returned/superseded work, or only active branches',
            'n / p — detail section; Tab — next pane; Enter on reference — inspect',
            'Backspace — return from reference; Esc — tree then close; Ctrl-C — close viewer',
        ]}))

    def open_panel(self, detail):
        if self.detail:
            self.back_stack.append(self.detail)
        self.install_detail(detail)

    async def select_node(self, args):
        if len(args) != 1 or args[0] not in self.navigation.by_id:
            raise ValueError('Use :node INVOCATION_ID from the current snapshot')
        self.navigation.selected = args[0]
        self.navigation.follow = False
        self.navigation.active_only = False
        self.navigation.focus = None
        self.navigation.update(self.view.snapshot)
        await self.selected_detail()

    def bindings(self):
        keys = KeyBindings()
        browsing = ~has_focus(self.command)

        @keys.add('c-c')
        def close(event):
            event.app.exit()

        @keys.add('escape')
        def escape(event):
            if event.app.layout.has_focus(self.tree_window):
                event.app.exit()
            else:
                event.app.layout.focus(self.tree_window)

        @keys.add('tab')
        def tab(event):
            panes = [self.tree_window]
            if self.detail_visible:
                panes.extend([self.details, self.links_window])
            panes.append(self.command)
            index = next((i for i, p in enumerate(panes) if event.app.layout.has_focus(p)), 0)
            event.app.layout.focus(panes[(index + 1) % len(panes)])

        @keys.add(':', filter=browsing)
        def prompt(event):
            event.app.layout.focus(self.command)

        @keys.add('up', filter=has_focus(self.tree_window))
        @keys.add('down', filter=has_focus(self.tree_window))
        def move(event):
            self.navigation.move(-1 if event.key_sequence[0].key == 'up' else 1)
            self.task(self.selected_detail())

        @keys.add('left', filter=has_focus(self.tree_window))
        @keys.add('right', filter=has_focus(self.tree_window))
        def fold(event):
            (self.navigation.collapse if event.key_sequence[0].key == 'left' else self.navigation.expand)()
            self.task(self.selected_detail())

        @keys.add('enter', filter=has_focus(self.tree_window))
        def details(event):
            self.detail_visible = True
            event.app.layout.focus(self.details)

        @keys.add('up', filter=has_focus(self.links_window))
        @keys.add('down', filter=has_focus(self.links_window))
        def link_move(event):
            delta = -1 if event.key_sequence[0].key == 'up' else 1
            self.link_index = max(0, min(len(self.detail.links) - 1, self.link_index + delta)) if self.detail else 0

        @keys.add('enter', filter=has_focus(self.links_window))
        def link_open(event):
            if self.detail and self.detail.links and self.detail.links[self.link_index].domain == 'campaign':
                self.task(self.execute('campaign ' + self.detail.links[self.link_index].identity))
            else:
                self.task(self.open_link())

        @keys.add('backspace', filter=browsing)
        def back(event):
            if self.back_stack:
                self.install_detail(self.back_stack.pop())

        @keys.add('n', filter=browsing)
        @keys.add('p', filter=browsing)
        def page(event):
            if self.detail:
                self.remember_scroll()
                self.page = (self.page + (1 if event.data == 'n' else -1)) % len(self.detail.sections)
                self.draw_detail()

        @keys.add(' ', filter=browsing)
        def toggle_detail(event):
            self.detail_visible = not self.detail_visible
            event.app.layout.focus(self.tree_window)

        @keys.add('z', filter=browsing)
        def focus(event):
            self.navigation.focus_selected()

        @keys.add('u', filter=browsing)
        def parent(event):
            self.navigation.up()

        @keys.add('f', filter=browsing)
        def follow(event):
            self.navigation.follow = not self.navigation.follow
            self.task(self.refresh())

        @keys.add('a', filter=browsing)
        def all_branches(event):
            self.navigation.active_only = not self.navigation.active_only
            self.navigation.focus = None
            visible = [node.identity for node, _ in self.navigation.visible()]
            if self.navigation.selected not in visible and visible:
                self.navigation.selected = visible[0]
            self.task(self.selected_detail())

        @keys.add('l', filter=browsing)
        def live(event):
            self.task(self.execute('live'))

        @keys.add('h', filter=browsing)
        def history(event):
            if self.view:
                self.controller.hold(self.view)
                self.back_stack.clear()
                self.task(self.refresh())

        @keys.add('[', filter=browsing)
        @keys.add(']', filter=browsing)
        def step(event):
            if self.view:
                self.controller.step(self.view, -1 if event.data == '[' else 1)
                self.back_stack.clear()
                self.task(self.refresh())

        return keys

    def run(self):
        return self.application.run(pre_run=lambda: self.task(self.watch()))
