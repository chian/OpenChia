"""Domain-neutral presentation values shared by terminal and shell clients."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Link:
    label: str
    domain: str
    identity: str


@dataclass(frozen=True)
class Node:
    identity: str
    parent: str | None
    label: str
    status: str
    summary: str
    counters: dict[str, int] = field(default_factory=dict)


@dataclass
class Snapshot:
    domain: str
    identity: str
    title: str
    position: dict[str, Any]
    nodes: list[Node]
    timeline: list[dict[str, Any]]
    links: list[Link] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


@dataclass
class Detail:
    identity: str
    domain: str
    title: str
    sections: dict[str, Any]
    links: list[Link] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


def display_text(value: str) -> str:
    """Persisted model output is data, including terminal control characters."""
    return ''.join(c if c in '\n\t' or (c.isprintable() and c != '\x7f')
                   else f'\\u{ord(c):04x}' for c in value)
