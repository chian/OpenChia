"""Read immutable published Run files without taking execution claim locks."""

import json
import re
from threading import RLock

from .archive import InspectionError, canonical_hash, record_context


def registration_path(root, run_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise InspectionError('Invalid Run identity')
    return root / 'episode_runs' / 'registrations' / f'{run_id}.json'


def read_json(path):
    if path.is_symlink() or not path.is_file():
        raise InspectionError(f'Published record unavailable: {path.name}')
    with record_context(f'published record {path.name}'):
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise InspectionError(f'Invalid record: {path.name}')
    return value


def read_registration(root, run_id):
    registration = read_json(registration_path(root, run_id))
    with record_context(f'Run registration {run_id}'):
        if registration['run_id'] != run_id or not isinstance(registration['registration_hash'], str):
            raise InspectionError(f'Run registration identity/hash is invalid: {run_id}')
        predecessor = registration.get('resume_from')
        if predecessor is not None and (not isinstance(predecessor, dict)
                                        or not isinstance(predecessor.get('run_id'), str)):
            raise InspectionError(f'Run registration predecessor is invalid: {run_id}')
    return registration


class RunCatalog:
    """Registration discovery isolates bad files and reuses unchanged publications."""

    def __init__(self, root):
        self.root = root
        self._snapshot = None
        self._lock = RLock()

    def version(self):
        result = []
        directory = self.root / 'episode_runs' / 'registrations'
        for path in sorted(directory.glob('*.json')):
            if path.name.startswith('.'):
                continue
            try:
                stat = path.lstat()
                result.append((path.name, stat.st_mtime_ns, stat.st_size, stat.st_ino))
            except OSError as exc:
                result.append((path.name, str(exc)))
        return tuple(result)

    def snapshot(self):
        version = self.version()
        with self._lock:
            if self._snapshot is not None and self._snapshot[0] == version:
                return self._snapshot
            registrations, gaps = [], []
            for name, *_ in version:
                try:
                    registrations.append(read_registration(self.root, name[:-5]))
                except (InspectionError, OSError) as exc:
                    gaps.append(f'Skipped Run registration {name}: {exc}')
            self._snapshot = version, tuple(registrations), tuple(gaps)
            return self._snapshot


def read_run(root, run_id, event=None):
    registration = read_registration(root, run_id)
    path = root / 'episode_runs' / 'events' / run_id
    # Publication uses temporary dotfiles followed by an atomic rename/link.
    # Freeze the list once; a concurrent append belongs to the next refresh.
    paths = sorted(p for p in path.glob('*.json') if re.fullmatch(r'\d{20}\.json', p.name))
    if event is not None and (event < 0 or event >= len(paths)):
        raise InspectionError(f'Run event {event} is unavailable')
    selected = paths if event is None else paths[:event + 1]
    events, previous = [], None
    for ordinal, path in enumerate(selected):
        record = read_json(path)
        with record_context(f'Run {run_id} event {ordinal}'):
            if (not isinstance(record['payload'], dict) or not isinstance(record['event_id'], str)
                    or not isinstance(record['kind'], str)
                    or (record['episode_id'] is not None and not isinstance(record['episode_id'], str))):
                raise InspectionError(f'Invalid Run event fields: {run_id} event {ordinal}')
            digest = canonical_hash({k: v for k, v in record.items() if k != 'event_hash'})
        if (path.name != f'{ordinal:020d}.json' or record.get('sequence') != ordinal
                or record.get('run_id') != run_id
                or record.get('registration_hash') != registration.get('registration_hash')
                or record.get('previous_event_hash') != previous
                or digest != record.get('event_hash')):
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
