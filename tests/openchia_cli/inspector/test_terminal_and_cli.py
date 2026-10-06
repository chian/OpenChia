"""Real prompt_toolkit input loop and installed command dispatch over recorded data."""

import asyncio
import json
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from openchia_cli.inspector.refiner import Refiner
from openchia_cli.inspector.refiner_controller import RefinerController
from openchia_cli.inspector.terminal import InspectorTerminal
from openchia_cli.inspector.model import display_text
from openchia_cli.openchia_commands import OpenChiaCommandMixin


async def until(predicate):
    deadline = asyncio.get_running_loop().time() + 15
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError('Terminal did not reach its requested state')
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_keyboard_navigation_history_and_reference_context(observer_home, campaign, monkeypatch):
    campaign.implementer()
    controller = RefinerController(Refiner(observer_home))
    with create_pipe_input() as pipe:
        terminal = InspectorTerminal(controller, input=pipe, output=DummyOutput())
        task = asyncio.create_task(terminal.application.run_async(
            pre_run=lambda: terminal.task(terminal.watch())))
        try:
            await until(lambda: terminal.detail is not None and not terminal.loading)
            iid = campaign.current_invocation.value
            assert terminal.navigation.selected == iid
            pipe.send_text('a')
            await until(lambda: not terminal.navigation.active_only)
            pipe.send_text('a')
            await until(lambda: terminal.navigation.active_only)
            pipe.send_text('z')
            await until(lambda: terminal.navigation.focus == iid)
            pipe.send_text('u')
            await until(lambda: terminal.navigation.focus != iid)
            pipe.send_text('h')
            await until(lambda: terminal.view.snapshot.position['mode'] == 'history' and not terminal.loading)
            held_step = terminal.view.snapshot.position['step']
            pipe.send_text('[')
            await until(lambda: terminal.view.snapshot.position['step'] == held_step - 1 and not terminal.loading)
            pipe.send_text(']')
            await until(lambda: terminal.view.snapshot.position['step'] == held_step and not terminal.loading)
            pipe.send_text('\t\t\r')
            await until(lambda: terminal.detail.domain == 'target_workflow')
            assert terminal.view.snapshot.position['mode'] == 'history'
            pipe.send_bytes(b'\x7f')
            await until(lambda: terminal.detail.domain == 'refiner')
            terminal.page = list(terminal.detail.sections).index('assignment')
            terminal.draw_detail()
            terminal.details.buffer.cursor_position = 200
            terminal.details.window.vertical_scroll = 2
            await terminal.refresh()
            assert terminal.details.buffer.cursor_position == 200
            assert terminal.detail.identity == iid
            await terminal.execute('campaigns')
            assert terminal.detail.domain == 'catalog'
            pipe.send_bytes(b'\x7f')
            await until(lambda: terminal.detail.domain == 'refiner')
            captured = terminal.view
            capture = controller.capture
            started = asyncio.Event()
            release = threading.Event()
            loop = asyncio.get_running_loop()

            def delayed_capture():
                result = capture()
                loop.call_soon_threadsafe(started.set)
                if not release.wait(15):
                    raise AssertionError('Refresh was not released')
                return result

            with monkeypatch.context() as patch:
                patch.setattr(controller, 'capture', delayed_capture)
                refresh = asyncio.create_task(terminal.refresh())
                try:
                    await asyncio.wait_for(started.wait(), 15)
                    terminal.link_index = 0
                    await terminal.open_link()
                    assert terminal.detail.domain == 'target_workflow'
                finally:
                    release.set()
                    await asyncio.wait_for(refresh, 15)
                assert terminal.view is captured
                assert terminal.detail.domain == 'target_workflow'
            pipe.send_bytes(b'\x7f')
            await until(lambda: terminal.detail.domain == 'refiner')
            pipe.send_text('l')
            await until(lambda: terminal.view.snapshot.position['mode'] == 'live' and not terminal.loading)
            assert 'LIVE' in terminal.header()
            await terminal.execute('at 0')
            assert not terminal.navigation.snapshot.nodes
            assert terminal.detail is None
            assert terminal.details.text == ''
            pipe.send_bytes(b'\x03')
            await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                terminal.application.exit()
                await task


@pytest.mark.asyncio
async def test_shell_entry_and_slash_dispatch_share_projection_without_host_creation(observer_home, campaign, monkeypatch):
    campaign.implementer()
    expected = Refiner(observer_home).capture().snapshot
    result = subprocess.run([sys.executable, '-m', 'openchia_cli.openchia_main', 'refiner', 'tree',
                             '--home', str(observer_home), '--json'], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data['nodes'] == expected.as_dict()['nodes']
    text = subprocess.run([sys.executable, '-m', 'openchia_cli.openchia_main', 'refiner', 'tree',
                           '--home', str(observer_home), '--at', str(expected.position['step'])],
                          capture_output=True, text=True, timeout=30)
    assert text.returncode == 0
    assert all(node['identity'] in text.stdout for node in data['nodes'])
    output = []
    cli = SimpleNamespace(_openchia_host=None, _print_openchia=output.append)
    monkeypatch.setenv('HERMES_HOME', str(observer_home))
    handler = OpenChiaCommandMixin._openchia_command_dispatch['/refiner']
    assert getattr(OpenChiaCommandMixin, handler)(cli, '/refiner tree --json')
    assert json.loads(output[0])['nodes'] == data['nodes']
    assert cli._openchia_host is None
    assert '\x1b' not in display_text('untrusted\x1b[2J\x07')
