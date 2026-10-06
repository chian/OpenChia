"""Selection and expansion survive refresh independently of domain readers."""

from .model import Snapshot


class Navigation:
    def __init__(self):
        self.selected = None
        self.focus = None
        self.expanded = set()
        self.follow = True
        self.active_only = False
        self.snapshot = None

    def update(self, snapshot: Snapshot):
        previous = self.by_id
        self.snapshot = snapshot
        nodes = self.by_id
        if self.focus not in nodes:
            self.focus = None
        if self.follow:
            active = [n for n in snapshot.nodes if n.status == 'active']
            if active:
                self.selected = active[-1].identity
                self.focus = None
        while self.selected not in nodes and self.selected in previous:
            self.selected = previous[self.selected].parent
        if self.selected not in nodes:
            self.selected = next(iter(nodes), None)
        self.expanded.intersection_update(nodes)
        parent = nodes[self.selected].parent if self.selected else None
        seen = set()
        while parent in nodes and parent not in seen:
            seen.add(parent)
            self.expanded.add(parent)
            parent = nodes[parent].parent

    @property
    def by_id(self):
        return {n.identity: n for n in self.snapshot.nodes} if self.snapshot else {}

    def visible(self):
        nodes = self.by_id
        if self.active_only:
            included = {n.identity for n in nodes.values() if n.status in {'active', 'waiting', 'ready', 'needs_parent_decision'}}
            if not self.follow and self.selected in nodes:
                included.add(self.selected)
            pending = list(included)
            while pending:
                parent = nodes[pending.pop()].parent
                if parent in nodes and parent not in included:
                    included.add(parent)
                    pending.append(parent)
            if included:
                nodes = {key: value for key, value in nodes.items() if key in included}
        children = {}
        for node in nodes.values():
            children.setdefault(node.parent, []).append(node)
        roots = ([nodes[self.focus]] if self.focus in nodes else
                 [n for n in nodes.values() if n.parent not in nodes])
        result, seen = [], set()
        stack = [(n, 0) for n in reversed(roots)]
        while stack:
            node, depth = stack.pop()
            if node.identity in seen:
                continue
            seen.add(node.identity)
            result.append((node, depth))
            if node.identity in self.expanded:
                stack.extend((n, depth + 1) for n in reversed(children.get(node.identity, [])))
        return result

    def move(self, offset):
        rows = [n.identity for n, _ in self.visible()]
        if not rows:
            return
        index = rows.index(self.selected) if self.selected in rows else 0
        self.selected = rows[max(0, min(len(rows) - 1, index + offset))]
        self.follow = False

    def collapse(self):
        self.follow = False
        if self.selected in self.expanded:
            self.expanded.remove(self.selected)
        elif self.selected in self.by_id:
            self.selected = self.by_id[self.selected].parent or self.selected

    def expand(self):
        if self.selected:
            self.expanded.add(self.selected)
        self.follow = False

    def focus_selected(self):
        self.focus = self.selected
        self.expand()

    def up(self):
        if self.focus in self.by_id:
            self.focus = self.by_id[self.focus].parent
        self.follow = False
