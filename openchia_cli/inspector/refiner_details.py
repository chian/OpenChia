"""Evidence drill-down at the projection's frozen observation boundary."""

from .archive import InspectionError, ref_id
from .model import Detail, Link
from . import run_reader


def references(value):
    found = {}
    pending = [(value, '')]
    while pending:
        item, path = pending.pop()
        if isinstance(item, dict):
            artifact = item.get('artifact_id')
            if isinstance(artifact, str):
                found[('artifact', artifact)] = Link(path or 'Artifact', 'artifact', artifact)
            run = item.get('run_id')
            if isinstance(run, str):
                found[('run', run)] = Link(path or 'Run', 'run', run)
            pending.extend((child, f'{path}.{key}' if path else key)
                           for key, child in reversed(item.items()))
            check = item.get('check_key')
            if isinstance(check, str):
                found[('artifact', check)] = Link('Check', 'artifact', check)
        elif isinstance(item, list):
            pending.extend((child, f'{path}[{index}]') for index, child in reversed(list(enumerate(item))))
    return list(found.values())


_DETAIL_KINDS = (
    'attempt', 'unit_receipt', 'parent_report', 'observation', 'change', 'design_plan',
    'proposal_rejection', 'coding_activity', 'coding_turn', 'measure_prerequisite',
    'parent_assessment', 'evaluation', 'evaluation_run', 'evaluation_source',
)


def assignment_detail(view, identity):
    assignment = view.assignments.get(identity)
    if assignment is None:
        raise InspectionError(f'Invocation {identity} is unavailable at this position')
    node = next((n for n in view.snapshot.nodes if n.identity == identity), None)
    if node is None:
        raise InspectionError(f'Invocation {identity} has no recorded tree node')
    kinds = [f'refinement.{kind}.v1' for kind in _DETAIL_KINDS]
    records = view.archive.records(view.duet, view.cutoff, kinds, related=(identity, assignment.identity))
    admitted = {row['record_id']: row['status'] for row in view.index.values()}
    committed_attempts = {attempt.identity for _, attempt in view.operations}
    for _, attempt in view.operations:
        if attempt.body['action'] == 'apply_change':
            changed = ref_id(attempt.body['payload'].get('change'))
            if changed:
                admitted[changed] = 'applied'
    activity, iterations, checks, reports, rejections, changes = [], [], [], [], [], []
    destinations = {'unit_receipt': iterations, 'parent_report': reports, 'observation': checks,
                    'parent_assessment': checks, 'evaluation': checks, 'evaluation_run': checks,
                    'evaluation_source': checks, 'proposal_rejection': rejections, 'change': changes}
    for item in records:
        kind = item.kind.split('.')[1]
        status = ('committed' if item.identity in committed_attempts else admitted.get(item.identity, 'recorded'))
        destinations.get(kind, activity).append({
            'artifact_id': item.identity, 'kind': kind, 'recorded_at': item.created_at,
            'record_status': status, 'record': item.record,
        })
    sections = {
        'summary': {'goal': node.summary, 'recorded_status': node.status,
                    'completed_iterations': node.counters['completed_iterations'],
                    'candidate_revision': view.candidate_id,
                    'meaning': 'Iterations count activity. Returned does not imply accepted. Recorded proposals are not admitted changes.'},
        'assignment': assignment.record, 'activity': activity, 'iterations': iterations,
        'candidate_changes': changes, 'checks': checks, 'rejections': rejections, 'reports': reports,
    }
    unique = {}
    for link in [*view.snapshot.links, *view.run_links(), *references(sections)]:
        if link.identity != assignment.identity:
            unique.setdefault((link.domain, link.identity), link)
    links = list(unique.values())
    return Detail(identity, 'refiner', f'{node.label}: {node.summary}', sections, links, list(view.snapshot.gaps))


def reference_detail(view, domain, identity):
    if domain == 'run':
        return run_detail(view, identity)
    if domain != 'artifact':
        raise InspectionError(f'Unsupported reference domain: {domain}')
    item = view.artifact(identity)
    domain = {'refinement.target_workflow.v1': 'target_workflow',
              'refinement.candidate.v1': 'candidate',
              'refinement.assignment.v1': 'refiner'}.get(item.kind, 'evidence')
    sections = {'record': item.record, 'provenance': {
        'kind': item.kind, 'content_hash': item.content_hash, 'created_at': item.created_at,
        'artifact_ordinal': item.ordinal,
    }}
    if domain == 'candidate':
        parent = ref_id(item.body.get('parent_candidate_ref'))
        before = view.artifact(parent).body['files'] if parent else {}
        after = item.body['files']
        changes = [{'path': path, 'before': before.get(path), 'after': after.get(path)}
                   for path in sorted(before.keys() | after.keys()) if before.get(path) != after.get(path)]
        sections = {'summary': {'candidate_revision': item.identity, 'parent_candidate': parent,
                                'changed_files': len(changes), 'meaning': 'An implementation revision; changes alone do not establish acceptance.'},
                    'file_changes': changes, **sections}
    if domain == 'target_workflow':
        episodes = item.body.get('workflow', {}).get('episodes', [])
        topology = [{'local_id': episode.get('local_id'), 'parent_local_id': episode.get('parent_local_id'),
                     'goal': episode.get('contract', {}).get('goal'),
                     'result': episode.get('contract', {}).get('result')}
                    for episode in episodes]
        sections = {'summary': {'workflow_identity': item.body.get('artifact_id'),
                                'workflow_revision': item.body.get('revision'),
                                'episodes': len(episodes),
                                'meaning': 'The approved Target Workflow being built; separate from Refiner assignments.'},
                    'episode_topology': topology, **sections}
    return Detail(identity, domain, f'{domain.replace("_", " ").title()} · {identity}',
                  sections, [link for link in references(item.record) if link.identity != identity])


def run_detail(view, identity):
    same_run = view.run and view.run[0]['run_id'] == identity
    if view.snapshot.position['mode'] == 'history' and not same_run:
        known = {link.identity for link in view.run_links()}
        for row in view.entries('evaluation_run'):
            known.update(link.identity for link in references(view.artifact(row['record_id']).record)
                         if link.domain == 'run')
        if identity not in known:
            raise InspectionError('Run is not recorded at this historical position')
        registration = run_reader.read_registration(view.archive.root, identity)
        return Detail(identity, 'run', f'Run · {identity}', {'registration': registration}, [],
                      ['No exact Run event boundary is established by this campaign cursor. '
                       'Select this Run with --run and --event to inspect its journal; current results are not substituted.'])
    registration, events = view.run if same_run else run_reader.read_run(view.archive.root, identity)
    status = events[-1]['payload'].get('terminal_status', 'no recorded terminal event') if events else 'no recorded events'
    sections = {'summary': {'recorded_status': status, 'last_event': events[-1]['sequence'] if events else None,
                           'meaning': 'Journal observation, not a process liveness probe.'},
                'registration': registration, 'events': events}
    return Detail(identity, 'run', f'Run · {identity}', sections, references(sections),
                  ['Run events have sequence numbers, not recorded wall-clock timestamps.'])
