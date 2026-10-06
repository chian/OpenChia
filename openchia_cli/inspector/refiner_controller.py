"""Refiner-specific selection commands for the shared terminal shell."""

from dataclasses import replace

from .archive import InspectionError
from .refiner import Selection


class RefinerController:
    def __init__(self, source, selection=Selection()):
        self.source, self.selection = source, selection

    @property
    def live(self):
        return self.selection.run is None and all(
            v is None for v in (self.selection.at, self.selection.at_time, self.selection.event))

    def capture(self):
        selected = self.selection
        view = self.source.capture(selected)
        if self.selection == selected:
            event = view.snapshot.position.get('run_event') if selected.run else selected.event
            self.selection = replace(selected, campaign=view.snapshot.identity, event=event)
        return view

    def campaigns(self):
        return self.source.campaigns(self.selection.duet)

    def command(self, action, args):
        setters = {
            'campaign': lambda value: Selection(campaign=value, duet=self.selection.duet),
            'run': lambda value: Selection(duet=self.selection.duet, run=value),
            'at': lambda value: replace(self.selection, at=int(value), at_time=None, run=None, event=None),
            'time': lambda value: replace(self.selection, at=None, at_time=value, run=None, event=None),
            'event': lambda value: replace(self.selection, at=None, at_time=None, event=int(value)),
        }
        if action == 'live' and not args:
            self.selection = replace(self.selection, at=None, at_time=None, event=None, run=None)
        elif action in setters and len(args) == 1:
            self.selection = setters[action](args[0])
        else:
            raise InspectionError('Use :help for inspector commands')

    def hold(self, view):
        pos = view.snapshot.position
        if self.selection.run and pos.get('run_event') is not None:
            self.selection = replace(self.selection, event=pos['run_event'], at=None, at_time=None)
        else:
            self.selection = Selection(campaign=view.snapshot.identity, duet=self.selection.duet, at=pos['step'])

    def step(self, view, delta):
        self.hold(view)
        if self.selection.run:
            self.selection = replace(self.selection, event=max(0, self.selection.event + delta))
        else:
            self.selection = replace(self.selection, at=max(0, min(view.snapshot.position['latest_step'], self.selection.at + delta)))
