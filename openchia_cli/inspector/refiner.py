"""Reconstruct Refiner state from the existing committed campaign delta chain."""

from copy import copy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import time

from .archive import Archive, InspectionError, record_context, ref_id
from .model import Link, Node, Snapshot
from . import run_reader


def parse_time(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise InspectionError('Use an ISO timestamp with a timezone') from exc
    if stamp.tzinfo is None:
        raise InspectionError('History time must include a timezone')
    return stamp.astimezone(timezone.utc)


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


@dataclass(frozen=True)
class Selection:
    campaign: str | None = None
    duet: str | None = None
    at: int | None = None
    at_time: str | None = None
    run: str | None = None
    event: int | None = None


class Refiner:
    def __init__(self, home):
        self.archive = Archive(home)
        self.runs = run_reader.RunCatalog(self.archive.root)

    def campaigns(self, duet=None):
        return self.archive.campaigns(duet)

    def version(self, selection):
        return (*self.archive.progress(selection.campaign, selection.duet), self.runs.version())

    def capture(self, selection=Selection()):
        with record_context(f'Refiner campaign {selection.campaign or "selection"}'):
            campaigns = self.campaigns(selection.duet)
            if not campaigns:
                raise InspectionError('No recorded refinement campaigns in this profile')
            if selection.event is not None and selection.run is None:
                raise InspectionError('--event requires --run')
            if selection.run and (selection.at is not None or selection.at_time is not None):
                raise InspectionError('Run history uses --event; campaign history uses --at or --at-time without --run')
            if sum(x is not None for x in (selection.at, selection.at_time, selection.event)) > 1:
                raise InspectionError('Choose one historical cursor: --at, --at-time, or --event')
            run = None
            anchor = None
            if selection.run:
                run = run_reader.read_run(self.archive.root, selection.run, selection.event)
                anchor, anchor_event = run_reader.campaign_anchor(run[1])
                if anchor:
                    campaign_id = anchor['campaign_head']['campaign_id']
                else:
                    campaign_id = self._campaign_for_run(selection.run, campaigns)
            else:
                campaign_id = selection.campaign or campaigns[0]['campaign_id']
            if selection.campaign and selection.campaign != campaign_id:
                raise InspectionError('Selected Run belongs to a different campaign')
            head = next((row for row in campaigns if row['campaign_id'] == campaign_id), None)
            if head is None:
                raise InspectionError('Campaign unavailable in the selected profile/Duet')
            at = selection.at
            if selection.run:
                if anchor is None:
                    at = 0
                else:
                    at = anchor['campaign_head']['sequence']
            view = CampaignProjection(self.archive, head, self.runs, at=at, at_time=selection.at_time,
                                      historical=any(v is not None for v in (at, selection.at_time, selection.event)))
            view.run = run
            if anchor and (view.contract.identity != ref_id(anchor['campaign_ref'])
                           or view.candidate_id != anchor['campaign_head']['candidate_id']):
                raise InspectionError('Run campaign snapshot differs from the recorded campaign chain')
            if run:
                view.snapshot.position.update(run_id=selection.run,
                    run_event=run[1][-1]['sequence'] if run[1] else None)
                if anchor is None:
                    view.snapshot.nodes = []
                    view.assignments.clear()
                    view.snapshot.links = [Link('Selected Run', 'run', selection.run)]
                    view.snapshot.position.update(campaign_state_known=False, candidate_id=None)
                    view.snapshot.gaps.append('No campaign state is recorded by this Run event. The Run journal remains inspectable; no current campaign state is substituted.')
                if anchor:
                    view.snapshot.position['campaign_anchor_event'] = anchor_event
                    if anchor_event != view.snapshot.position['run_event']:
                        view.snapshot.gaps.append(f'Campaign state is last recorded at Run event {anchor_event}; no newer campaign snapshot by event {view.snapshot.position["run_event"]}.')
            return view

    def _campaign_for_run(self, run_id, campaigns):
        for head in campaigns:
            view = CampaignProjection(self.archive, head, self.runs)
            if any(link.identity == run_id for link in view.run_links()):
                return head['campaign_id']
        raise InspectionError('Run has no recorded association to a refinement campaign')


class CampaignProjection:
    def __init__(self, archive, head, runs, *, at=None, at_time=None, historical=False):
        self.archive, self.head = archive, head
        self.duet = head['duet_id']
        self.run = None
        timestamp = parse_time(at_time) if at_time else None
        with archive.connection() as db:
            # Re-read mutable head and immutable rows in one SQLite snapshot.
            self.head = dict(db.execute('SELECT * FROM refinement_campaign_heads WHERE campaign_id=?',
                                       (head['campaign_id'],)).fetchone())
            cutoff = db.execute('SELECT coalesce(max(rowid),0) FROM artifacts WHERE duet_id=?',
                                (self.duet,)).fetchone()[0]
            time_cutoff = cutoff
            if timestamp is not None:
                # Compare at the same precision as displayed ISO timestamps so
                # copying a timeline time cannot select the preceding commit.
                publications = db.execute(
                    'SELECT rowid,created_at FROM artifacts WHERE duet_id=? ORDER BY rowid DESC',
                    (self.duet,))
                time_cutoff = next((row[0] for row in publications
                                    if datetime.fromtimestamp(row[1], timezone.utc) <= timestamp), 0)
        run_version, self.registrations, run_gaps = runs.snapshot()
        self.version = self.head['latest_commit_id'], self.head['sequence'], cutoff, run_version
        records = archive.records(self.duet, cutoff, ['refinement.commit.v1'], campaign=head['campaign_id'])
        by_id = {record.identity: record for record in records}
        commits, seen = [], set()
        current = self.head['latest_commit_id']
        while current:
            if current in seen or current not in by_id:
                raise InspectionError('Campaign commit chain is missing or cyclic')
            seen.add(current)
            commit = by_id[current]
            commits.append(commit)
            current = ref_id(commit.body['previous_commit_ref'])
            if current and current in by_id and commit.body['previous_commit_ref']['content_hash'] != by_id[current].content_hash:
                raise InspectionError('Campaign predecessor hash differs')
        commits.reverse()
        self.cutoff = cutoff
        self.contract = self.artifact(self.head['contract_id'])
        initial = self.artifact(self.head['initial_candidate_id'])
        if time_cutoff < max(initial.ordinal, self.contract.ordinal):
            raise InspectionError('Campaign did not exist at this recorded time')
        if at is not None and (at < 0 or at > len(commits)):
            raise InspectionError(f'Campaign step {at} is unavailable (latest {len(commits)})')
        self.timeline = [{'step': 0, 'identity': self.contract.identity,
                          'time': utc(max(initial.created_at, self.contract.created_at)), 'action': 'campaign_started'}]
        self.index, self.credits, self.operations = {}, [], []
        candidate = self.head['initial_candidate_id']
        previous = None
        selected = (sum(commit.ordinal <= time_cutoff for commit in commits) if at is None else at)
        for ordinal, commit in enumerate(commits, 1):
            if (commit.body['sequence'] != ordinal or ref_id(commit.body['previous_commit_ref']) != previous):
                raise InspectionError(f'Campaign history is incomplete at step {ordinal}')
            previous = commit.identity
            attempt = self.artifact(ref_id(commit.body['attempt_ref']))
            self.timeline.append({'step': ordinal, 'identity': commit.identity, 'time': utc(commit.created_at),
                                  'action': attempt.body['action'], 'invocation_id': attempt.body['invocation_id']})
            if ordinal > selected:
                continue
            self.operations.append((commit, attempt))
            for delta in commit.body['deltas']:
                kind = delta['kind']
                if kind == 'index':
                    self.index[(delta['collection'], delta['key'])] = {**delta, 'sequence': ordinal}
                elif kind == 'head':
                    if delta['before'] != candidate:
                        raise InspectionError('Candidate history does not match its predecessor')
                    candidate = delta['after']
                elif kind == 'credit':
                    self.credits.append(delta)
                else:
                    raise InspectionError(f'Unsupported campaign delta: {kind}')
        if not historical and (len(commits) != self.head['sequence'] or previous != self.head['latest_commit_id']):
            raise InspectionError('Campaign head does not match its committed history')
        if at is not None:
            self.cutoff = commits[at - 1].ordinal if at else max(initial.ordinal, self.contract.ordinal)
        elif timestamp is not None:
            self.cutoff = time_cutoff
        self.candidate_id = candidate
        self.snapshot = Snapshot('refiner', head['campaign_id'], 'IterativeEpisodeRefiner',
            {'mode': 'history' if historical else 'live', 'step': selected,
             'latest_step': len(commits), 'time': self.timeline[selected]['time'],
             'observed_at': utc(time.time()), 'artifact_cutoff': self.cutoff,
             'duet_id': self.duet, 'candidate_id': candidate, 'home': str(archive.home)},
            [], self.timeline[:selected + 1],
            [Link('Target Workflow', 'artifact', ref_id(self.contract.body['target_workflow_ref'])),
             Link('Candidate revision', 'artifact', candidate)])
        if timestamp is not None:
            self.snapshot.position['selected_time'] = timestamp.isoformat()
        self.snapshot.gaps.extend(run_gaps)
        self.assignments = {}
        self._details = {}
        self._run_links = None
        self._build_nodes()

    def refreshed(self):
        result = copy(self)
        result.snapshot = replace(self.snapshot, position={**self.snapshot.position, 'observed_at': utc(time.time())})
        return result

    def artifact(self, identity):
        if not identity:
            raise InspectionError('Record has no artifact identity')
        return self.archive.artifact(identity, self.duet, self.cutoff)

    def entries(self, collection):
        return [row for (name, _), row in self.index.items() if name == collection]

    def _build_nodes(self):
        invocations = self.entries('invocation')
        by_assignment = {row['record_id']: row['key'] for row in invocations}
        units = {}
        for row in self.entries('unit'):
            unit = self.artifact(row['record_id'])
            iid = unit.body.get('invocation_id', unit.record.get('invocation_id'))
            units[iid] = units.get(iid, 0) + 1
        for row in invocations:
            assignment = self.artifact(row['record_id'])
            self.assignments[row['key']] = assignment
            body = assignment.body
            parent_ref = ref_id(body['parent_assignment_ref'])
            if parent_ref and parent_ref not in by_assignment:
                self.snapshot.gaps.append(f'Parent assignment unavailable for {row["key"]}')
            try:
                goal = self.artifact(ref_id(body['goal_record_ref'])).body.get('goal', '')
            except InspectionError as exc:
                goal = 'Goal unavailable'
                self.snapshot.gaps.append(str(exc))
            if not isinstance(goal, str):
                raise InspectionError(f'Assignment {assignment.identity} goal must be text')
            assignment_entry = self.index.get(('assignment', assignment.identity), {})
            state = 'superseded' if assignment_entry.get('status') == 'superseded' else row['status']
            self.snapshot.nodes.append(Node(row['key'], by_assignment.get(parent_ref),
                body['role'].title(), state, goal, {'completed_iterations': units.get(row['key'], 0)}))

    def run_links(self):
        with record_context(f'Run links for campaign {self.snapshot.identity}'):
            if self._run_links is not None:
                return self._run_links
            jobs = self.archive.records(self.duet, self.cutoff, ['experiment.refinement_job.v1'])
            roots = {job.body['registration']['run_id'] for job in jobs
                     if ref_id(job.body.get('campaign_ref')) == self.contract.identity}
            included = set(roots)
            # Continuation identity follows the persisted predecessor, across any number of restarts.
            changed = True
            while changed:
                changed = False
                for reg in self.registrations:
                    predecessor = (reg.get('resume_from') or {}).get('run_id')
                    if predecessor in included and reg['run_id'] not in included:
                        included.add(reg['run_id'])
                        changed = True
            if self.snapshot.position['mode'] == 'history':
                # A registration has no wall clock. Only advertise descendants that
                # are explicitly referenced by evidence already visible at this cursor.
                records = self.archive.records(self.duet, self.cutoff,
                    ['experiment.refinement_result_attempt.v1', 'refinement.model_proposal.v1', 'refinement.coding_activity.v1'])
                visible = {r.body.get('run_id') for r in records}
                included.intersection_update(roots | visible)
            self._run_links = [Link('Refiner Run', 'run', value) for value in sorted(included)]
            return self._run_links

    def detail(self, identity):
        from .refiner_details import assignment_detail
        if identity not in self._details:
            with record_context(f'assignment {identity}'):
                self._details[identity] = assignment_detail(self, identity)
        return self._details[identity]

    def reference(self, domain, identity):
        from .refiner_details import reference_detail
        with record_context(f'{domain} {identity}'):
            return reference_detail(self, domain, identity)
