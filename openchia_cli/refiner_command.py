"""Independent Refiner viewer: python -m openchia_cli.refiner_command --help."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shlex
import sys

from openchia_cli.inspector.archive import InspectionError
from openchia_cli.inspector.refiner import Refiner, Selection
from openchia_cli.inspector.render import detail_text, position_text, tree_text
from openchia_cli.inspector.model import display_text


def parser():
    result = argparse.ArgumentParser(prog='openchia refiner', description='Read-only live and historical Refiner inspection. No model calls or execution.')
    result.add_argument('action', nargs='?', default='view', choices=('view', 'list', 'tree', 'show', 'history', 'runs'))
    result.add_argument('--home', type=Path, help='Owning profile home; defaults to the currently bound profile')
    result.add_argument('--duet', help='Filter campaigns by owning Duet identity')
    result.add_argument('--campaign', help='Campaign identity (default: most recently created in this profile/Duet)')
    result.add_argument('--run', help='Inspect a recorded Refiner Run, including a continuation')
    cursor = result.add_mutually_exclusive_group()
    cursor.add_argument('--at', type=int, help='Campaign commit step; 0 is the initial campaign')
    cursor.add_argument('--at-time', help='Recorded ISO timestamp, including timezone')
    cursor.add_argument('--event', type=int, help='Run event number; requires --run')
    result.add_argument('--node', help='Stable invocation identity to inspect or focus')
    result.add_argument('--reference', help='Follow artifact:ID or run:ID at the selected historical position')
    result.add_argument('--section', help='Show one detail section, e.g. assignment, iterations, checks, or reports')
    output = result.add_mutually_exclusive_group()
    output.add_argument('--json', action='store_true', help='Machine-readable output from the same projection')
    output.add_argument('--plain', action='store_true', help='Print a snapshot without opening the interactive viewer')
    return result


def main(argv=None, *, emit=print, default_home=None, default_duet=None):
    args = parser().parse_args(argv)
    try:
        if args.home is None:
            from hermes_constants import get_hermes_home

            args.home = default_home or get_hermes_home()
        source = Refiner(args.home)
        selection = Selection(args.campaign, args.duet or default_duet, args.at, args.at_time, args.run, args.event)
        if args.action == 'list':
            data = source.campaigns(selection.duet)
            emit(json.dumps(data, ensure_ascii=False, indent=2) if args.json else display_text(
                '\n'.join(f'{r["campaign_id"]} · Duet {r["duet_id"]} · step {r["sequence"]}' for r in data) or 'No recorded campaigns.'))
            return 0
        if args.action == 'view' and not (args.json or args.plain) and sys.stdin.isatty():
            from openchia_cli.inspector.refiner_controller import RefinerController
            from openchia_cli.inspector.terminal import InspectorTerminal

            terminal = InspectorTerminal(RefinerController(source, selection))
            terminal.navigation.selected = args.node
            terminal.navigation.follow = args.node is None
            terminal.run()
            return 0
        view = source.capture(selection)
        if args.action == 'history':
            data = ([{'event': e['sequence'], 'kind': e['kind'], 'episode_id': e['episode_id'],
                      'identity': e['event_id']} for e in view.run[1]] if view.run else view.snapshot.timeline)
        elif args.action == 'runs':
            data = [asdict(link) for link in view.run_links()]
        elif args.action == 'show' or args.node or args.reference:
            if args.reference:
                domain, separator, identity = args.reference.partition(':')
                if not separator:
                    raise InspectionError('Use --reference artifact:ID or run:ID')
                detail = view.reference(domain, identity)
            elif args.node:
                detail = view.detail(args.node)
            else:
                raise InspectionError('show requires --node or --reference')
            if args.section and args.section not in detail.sections:
                raise InspectionError(f'Unknown section; choose: {", ".join(detail.sections)}')
            data = {'position': view.snapshot.position, 'detail': detail.as_dict()}
            if args.section:
                data['detail']['sections'] = {args.section: detail.sections[args.section]}
            if not args.json:
                emit(position_text(view.snapshot) + '\n' + detail_text(detail, args.section))
                return 0
        else:
            data = view.snapshot.as_dict()
            if not args.json:
                emit(tree_text(view.snapshot))
                return 0
        text = json.dumps(data, ensure_ascii=False, indent=2)
        emit(text if args.json else display_text(text))
        return 0
    except (InspectionError, OSError, ValueError) as exc:
        error = {'error': str(exc), 'kind': 'observation_unavailable'}
        emit(json.dumps(error) if args.json else display_text(f'Refiner inspection unavailable: {exc}'))
        return 2


def open_from_cli(cli, stripped):
    """Use an already-owned profile/Duet without creating or modifying a host."""
    host = getattr(cli, '_openchia_host', None)
    home = host.root.parent if host else None
    duet = host.identity.duet_id.value if host else None
    try:
        main(shlex.split(stripped.partition(' ')[2]), emit=cli._print_openchia,
             default_home=home, default_duet=duet)
    except SystemExit:
        # argparse help/errors must not terminate the owning Duet session.
        pass
    return True


if __name__ == '__main__':
    raise SystemExit(main())
