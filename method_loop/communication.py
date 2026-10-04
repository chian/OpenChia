"""Parent-owned reporting contracts, separate from audit and numerical credit.

Bindings describe the meaning of the requested measurements and information.
The method checks the declared return shape and known audit identities; the
binding's synthesis owns the task-specific interpretation of its evidence.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping

from .binding import _freeze_json, _text, _thaw_json


@dataclass(frozen=True)
class ReportContract:
    """Information requested before one child starts, in the parent's terms.

    ``measurements`` describes the requested judgments; it is not executable
    credit policy. ``information`` maps each required return field to its
    decision-relevant meaning. Domain admission remains in the binding.
    """

    decision: str
    measurements: Mapping[str, Any]
    information: Mapping[str, str]

    def __post_init__(self) -> None:
        _text(self.decision, "parent decision")
        if not isinstance(self.measurements, Mapping):
            raise TypeError("report measurements must be explicitly declared")
        if not isinstance(self.information, Mapping) or not self.information:
            raise ValueError("parent must declare the information its child returns")
        for name, meaning in self.information.items():
            _text(name, "report field")
            _text(meaning, "report field meaning")
        object.__setattr__(self, "measurements", _freeze_json(self.measurements, "report measurements"))
        object.__setattr__(self, "information", _freeze_json(self.information, "report information"))

    def as_record(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "measurements": _thaw_json(self.measurements),
            "information": _thaw_json(self.information),
        }

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> "ReportContract":
        if not isinstance(value, Mapping) or set(value) != {"decision", "measurements", "information"}:
            raise ValueError("report contract fields must be exact")
        return cls(**value)

    def admit(self, value: Mapping[str, Any], *, audit_identifiers: tuple[str, ...]) -> "ParentReport":
        """Reject, rather than mask, audit identifiers in the proposed synthesis."""
        report = ParentReport(self, value)
        report.exclude_audit_identifiers(audit_identifiers)
        object.__setattr__(report, "_audit_identifiers", audit_identifiers)
        return report


@dataclass(frozen=True)
class ParentReport:
    """Only the synthesized information requested by the invoking parent."""

    contract: ReportContract
    values: Mapping[str, Any]
    _audit_identifiers: tuple[str, ...] = field(default=(), init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.contract, ReportContract):
            raise TypeError("parent report requires its predeclared ReportContract")
        if not isinstance(self.values, Mapping) or set(self.values) != set(self.contract.information):
            raise ValueError("parent report must contain exactly the requested information")
        object.__setattr__(self, "values", _freeze_json(self.values, "parent report"))

    def exclude_audit_identifiers(self, identifiers: tuple[str, ...], *, inputs=None) -> None:
        """Compare against actual identities, not patterns or shortened aliases."""
        if not isinstance(identifiers, tuple) or any(not isinstance(item, str) or not item for item in identifiers):
            raise TypeError("audit identifiers must be a tuple of nonempty strings")

        def inspect(value: Any) -> None:
            if isinstance(value, str):
                if any(identifier in value for identifier in identifiers):
                    raise ValueError("parent report contains a child audit identity")
            elif isinstance(value, Mapping):
                for key, item in value.items():
                    inspect(key)
                    inspect(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    inspect(item)

        inspect(self.values if inputs is None else inputs)

    def validate_model_inputs(self, inputs: Mapping[str, Any]) -> None:
        """Apply the same identity boundary to the final declared model inputs."""
        self.exclude_audit_identifiers(self._audit_identifiers, inputs=inputs)

    def as_record(self) -> dict[str, Any]:
        return _thaw_json(self.values)
