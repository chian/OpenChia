"""Read immutable published Run files without taking execution claim locks."""

import json
import re

from .archive import InspectionError, canonical_hash


def run_path(root, run_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise InspectionError('Invalid Run identity')
    return root / 'episode_runs'


def read_json(path):
    if path.is_symlink() or not path.is_file():
        raise InspectionError(f'Published record unavailable: {path.name}')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise InspectionError(f'Invalid record: {path.name}')
    return value


def registrations(root):
    directory = root / 'episode_runs' / 'registrations'
    if not directory.exists():
        return []
    return [read_json(path) for path in sorted(directory.glob('*.json'))]


def read_run(root, run_id, event=None):
    directory = run_path(root, run_id)
    registration = read_json(directory / 'registrations' / f'{run_id}.json')
    if registration.get('run_id') != run_id:
        raise InspectionError('Run registration identity differs')
    path = directory / 'events' / run_id
    # Publication uses temporary dotfiles followed by an atomic rename/link.
    # Freeze the list once; a concurrent append belongs to the next refresh.
    paths = sorted(p for p in path.glob('*.json') if re.fullmatch(r'\d{20}\.json', p.name))
    if event is not None and (event < 0 or event >= len(paths)):
        raise InspectionError(f'Run event {event} is unavailable')
    selected = paths if event is None else paths[:event + 1]
    events, previous = [], None
    for ordinal, path in enumerate(selected):
        record = read_json(path)
        if (path.name != f'{ordinal:020d}.json' or record.get('sequence') != ordinal
                or record.get('run_id') != run_id
                or record.get('registration_hash') != registration.get('registration_hash')
                or record.get('previous_event_hash') != previous
                or canonical_hash({k: v for k, v in record.items() if k != 'event_hash'}) != record.get('event_hash')):
            raise InspectionError(f'Run journal has a gap or invalid hash at event {ordinal}')
        previous = record['event_hash']
        events.append(record)
    return registration, events


def campaign_anchor(events):
    """No wall-clock interpolation across independent stores is sound."""
    for event in reversed(events):
        state = event.get('payload', {}).get('session_state')
        if isinstance(state, dict) and state.get('kind') == 'refinement_session_state':
            return state, event['sequence']
    return None, None
