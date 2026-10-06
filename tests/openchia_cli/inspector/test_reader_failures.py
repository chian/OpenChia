"""Storage failures stay inspectable without taking down the terminal loop."""

from dataclasses import replace
import json
import sqlite3
import subprocess
import sys

import pytest
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from openchia_cli.inspector.archive import InspectionError, canonical_hash
from openchia_cli.inspector.model import Detail
from openchia_cli.inspector.refiner import Refiner
from openchia_cli.inspector.refiner_controller import RefinerController
from openchia_cli.inspector.terminal import InspectorTerminal
from openchia_cli.refiner_command import main


@pytest.mark.asyncio
async def test_unavailable_store_and_empty_view_remain_usable(tmp_path, monkeypatch):
    # An existing non-database file exercises real SQLite error conversion.
    root = tmp_path / 'openchia'
    root.mkdir()
    (root / 'authority.sqlite3').write_bytes(b'not a SQLite database')
    output = []
    assert main(['tree', '--home', str(tmp_path), '--json'], emit=output.append) == 2
    assert json.loads(output[-1])['kind'] == 'observation_unavailable'

    def cannot_connect(*args, **kwargs):
        raise sqlite3.OperationalError('reader cannot open WAL sidecar')

    monkeypatch.setattr(sqlite3, 'connect', cannot_connect)
    with create_pipe_input() as pipe:
        terminal = InspectorTerminal(RefinerController(Refiner(tmp_path)), input=pipe, output=DummyOutput())
        await terminal.refresh()
        assert terminal.view is None and 'WAL sidecar' in terminal.status
        await terminal.execute('runs')
        assert 'Select an available campaign' in terminal.status
        await terminal.execute('node missing')
        assert 'current snapshot' in terminal.status
        await terminal.open_link()
        terminal.install_detail(Detail('empty', 'evidence', 'Empty record', {}))
        assert 'No recorded sections' in terminal.detail_header()
        terminal.remember_scroll()
        await terminal.execute('help')
        assert terminal.detail.domain == 'help'


@pytest.mark.asyncio
async def test_invalid_persisted_structures_report_their_record_context(observer_home, campaign):
    for identity, kind, record, message in (
        ('bad_schema', 'refinement.candidate.v1', {'schema_id': None}, 'schema_id'),
        ('bad_body', 'refinement.candidate.v1', {'body': []}, 'body'),
        ('missing_files', 'refinement.candidate.v1', {}, 'files'),
    ):
        campaign.duets.put_artifact(artifact_id=identity, duet_id=campaign.session.duet_id,
            kind=kind, revision=1, record=record, content_hash=canonical_hash(record))
        output = []
        assert main(['show', '--home', str(observer_home), '--reference', f'artifact:{identity}', '--json'],
                    emit=output.append) == 2
        error = json.loads(output[-1])
        assert error['kind'] == 'observation_unavailable'
        assert identity in error['error'] and message in error['error']

    # Corrupt only fixture records; no production writer accepts these values.
    with sqlite3.connect(campaign.duets.path) as db:
        db.execute("UPDATE artifacts SET record_json=? WHERE artifact_id='bad_schema'", ('{"value": NaN}',))
    with pytest.raises(InspectionError, match='bad_schema'):
        Refiner(observer_home).capture().reference('artifact', 'bad_schema')

    view = Refiner(observer_home).capture()
    iid = view.snapshot.nodes[0].identity
    view.snapshot = replace(view.snapshot, nodes=[])
    with pytest.raises(InspectionError, match='no recorded tree node'):
        view.detail(iid)

    # A correctly hashed commit can still carry an unusable structure.
    with sqlite3.connect(campaign.duets.path) as db:
        commit_id, payload = db.execute(
            'SELECT a.artifact_id,a.record_json FROM artifacts a JOIN refinement_campaign_heads h '
            'ON a.artifact_id=h.latest_commit_id WHERE h.campaign_id=?', (campaign.campaign_id.value,)).fetchone()
        record = json.loads(payload)
        del record['body']['deltas']
        db.execute('UPDATE artifacts SET record_json=?,content_hash=? WHERE artifact_id=?',
                   (json.dumps(record), canonical_hash(record), commit_id))
    output = []
    assert main(['tree', '--home', str(observer_home), '--json'], emit=output.append) == 2
    assert 'deltas' in json.loads(output[-1])['error']


def test_selection_recovers_when_a_cyclic_parent_chain_disappears():
    # Keep the regression bounded even on an implementation that spins forever.
    program = '''
from openchia_cli.inspector.model import Node, Snapshot
from openchia_cli.inspector.navigation import Navigation
nav = Navigation()
nav.follow = False
nav.update(Snapshot('test', 'old', '', {}, [
    Node('a', 'b', '', 'active', ''), Node('b', 'a', '', 'waiting', ''),
], []))
nav.update(Snapshot('test', 'new', '', {}, [Node('c', None, '', 'active', '')], []))
assert nav.selected == 'c'
assert [node.identity for node, _ in nav.visible()] == ['c']
'''
    subprocess.run([sys.executable, '-c', program], check=True, timeout=10)
