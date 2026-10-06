"""Text output is the same projection the interactive viewer navigates."""

import json

from .model import display_text
from .navigation import Navigation


def position_text(snapshot):
    pos = snapshot.position
    lines = [f'{snapshot.title} | {pos["mode"].upper()} | step {pos["step"]}/{pos["latest_step"]}',
             f'Campaign: {snapshot.identity}', f'Duet: {pos["duet_id"]}',
             f'Recorded: {pos["time"]} | refreshed: {pos["observed_at"]}',
             f'Candidate revision: {pos["candidate_id"]}']
    if pos.get('run_id'):
        lines.append(f'Run: {pos["run_id"]} | event: {pos["run_event"]}')
    if pos.get('selected_time'):
        lines.append(f'Selected time: {pos["selected_time"]}')
    return display_text('\n'.join(lines))


def tree_text(snapshot, *, focus=None):
    navigation = Navigation()
    navigation.follow = False
    navigation.update(snapshot)
    navigation.expanded = {node.identity for node in snapshot.nodes}
    navigation.focus = focus
    lines = [position_text(snapshot)]
    for node, depth in navigation.visible():
        goal = ' '.join(node.summary.split())
        if len(goal) > 140:
            goal = goal[:137] + '…'
        lines.append(f'{"  " * depth}{node.label} [{node.status}] '
                     f'iterations={node.counters.get("completed_iterations", 0)}: {goal}\n'
                     f'{"  " * depth}  id={node.identity}')
    lines.extend(f'GAP: {gap}' for gap in snapshot.gaps)
    return display_text('\n'.join(lines))


def detail_text(detail, section=None):
    if section is not None:
        if section not in detail.sections:
            raise ValueError(f'Unknown section {section}; choose: {", ".join(detail.sections)}')
        data = {section: detail.sections[section]}
        if section == 'summary' and isinstance(detail.sections[section], dict):
            return display_text('\n\n'.join(f'{key.replace("_", " ").title()}\n{value}'
                                          for key, value in detail.sections[section].items()))
    else:
        data = detail.as_dict()
    return display_text(json.dumps(data, ensure_ascii=False, indent=2))
