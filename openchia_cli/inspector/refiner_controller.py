"""Refiner-specific selection commands for the shared terminal shell."""

from dataclasses import replace
from threading import RLock

from .archive import InspectionError
from .refiner import Selection


class RefinerController:
    def __init__(self, source, selection=Selection()):
        self.source, self._selection = source, selection
        self._lock = RLock()
        self._cached = None

    @property
    def selection(self):
        with self._lock:
            return self._selection

    @property
    def live(self):
        selected = self.selection
        return selected.run is None and all(
            v is None for v in (selected.at, selected.at_time, selected.event))

    def capture(self):
        with self._lock:
            selected, cached = self._selection, self._cached
        # Poll publication boundaries before rebuilding a campaign. Run cursors
        # are explicitly held, so their journals are read only on navigation.
        if (cached is not None and selected == cached[0] and selected.run is None
                and self.source.version(selected) == cached[1].version):
            view = cached[1].refreshed()
        else:
            view = self.source.capture(selected)
        with self._lock:
            if self._selection == selected:
                event = view.snapshot.position.get('run_event') if selected.run else selected.event
                self._selection = replace(selected, campaign=view.snapshot.identity, event=event)
                self._cached = self._selection, view
        return view

    def campaigns(self):
        return self.source.campaigns(self.selection.duet)

    def command(self, action, args):
        with self._lock:
            self._command(action, args)

    def _command(self, action, args):
        setters = {
            'campaign': lambda value: Selection(campaign=value, duet=self.selection.duet),
            'run': lambda value: Selection(duet=self.selection.duet, run=value),
            'at': lambda value: replace(self.selection, at=int(value), at_time=None, run=None, event=None),
            'time': lambda value: replace(self.selection, at=None, at_time=value, run=None, event=None),
            'event': lambda value: replace(self.selection, at=None, at_time=None, event=int(value)),
        }
        if action == 'live' and not args:
            self._selection = replace(self.selection, at=None, at_time=None, event=None, run=None)
        elif action in setters and len(args) == 1:
            self._selection = setters[action](args[0])
        else:
            raise InspectionError('Use :help for inspector commands')

    def hold(self, view):
        with self._lock:
            self._hold(view)

    def _hold(self, view):
        pos = view.snapshot.position
        if self.selection.run and pos.get('run_event') is not None:
            self._selection = replace(self.selection, event=pos['run_event'], at=None, at_time=None)
        else:
            self._selection = Selection(campaign=view.snapshot.identity, duet=self.selection.duet, at=pos['step'])

    def step(self, view, delta):
        with self._lock:
            self._hold(view)
            if self.selection.run:
                self._selection = replace(self.selection, event=max(0, self.selection.event + delta))
            else:
                self._selection = replace(self.selection, at=max(0, min(view.snapshot.position['latest_step'], self.selection.at + delta)))
