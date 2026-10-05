"""Identity admission and marginal hypervolume credit for Episode results.

This module is the only numerical-method component that sees stable result
identities or declared result-column names.  It retains accepted identities,
admits observed/failed/excluded units, and exports the full-history incidence
sufficient statistics as frozen positional tuples.  Rarefaction receives only
that numeric boundary.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from function_library import FunctionImplementation, FunctionLibrary, LibraryFunction
from method_loop import ClosedRecord


# One position is (accepted distinct, observed incidence samples,
# frequency-of-frequencies indexed from zero through observed samples).
POSITION_ACCEPTED_DISTINCT = 0
POSITION_OBSERVED_SAMPLES = 1
POSITION_FREQUENCY_OF_FREQUENCIES = 2
POSITION_STATISTIC_WIDTH = 3

# Admission counts deliberately omit excluded units.  Exclusions are retained
# in the credit audit but are not numerical observations.
ADMISSION_OBSERVED = 0
ADMISSION_FAILED = 1
ADMISSION_STATISTIC_WIDTH = 2

PositionStatistics = tuple[int, int, tuple[int, ...]]
AdmissionStatistics = tuple[int, int]
_CLOSED_TOKEN = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_STABLE_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}_[0-9a-f]{24,64}$")


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _probability(value: object, name: str) -> float:
    number = _finite(value, name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return number


def _non_negative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _stable_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not _STABLE_ID.fullmatch(value):
        raise ValueError(f"{name} must be a stable opaque ID")
    return value


def _identities(values: Iterable[object], name: str) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = _stable_id(raw, name)
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


class AdmissionStatus(str, Enum):
    OBSERVED = "observed"
    FAILED = "failed"
    EXCLUDED = "excluded"


OBSERVED = AdmissionStatus.OBSERVED
FAILED = AdmissionStatus.FAILED
EXCLUDED = AdmissionStatus.EXCLUDED


class BandStatus(str, Enum):
    READY = "ready"
    INSUFFICIENT = "insufficient"
    UNIDENTIFIABLE = "unidentifiable"


@dataclass(frozen=True)
class NumericBand:
    """A non-negative numeric estimate and its uncertainty interval."""

    value: float
    lower: float
    upper: float
    uncertainty_alpha: float
    status: BandStatus

    def __post_init__(self) -> None:
        if not isinstance(self.status, BandStatus):
            raise ValueError("status must be a BandStatus")
        value = _finite(self.value, "band value")
        lower = _finite(self.lower, "band lower")
        upper = _finite(self.upper, "band upper")
        alpha = _finite(self.uncertainty_alpha, "band uncertainty_alpha")
        if self.status is BandStatus.READY:
            if not 0.0 <= lower <= value <= upper:
                raise ValueError(
                    "a ready band must satisfy 0 <= lower <= value <= upper"
                )
            if lower == value == upper:
                if alpha != 0.0:
                    raise ValueError("an exact band must have uncertainty_alpha 0")
            elif not 0.0 < alpha < 1.0:
                raise ValueError(
                    "an uncertain ready band requires 0 < uncertainty_alpha < 1"
                )
        elif (value, lower, upper, alpha) != (0.0, 0.0, 0.0, 0.0):
            raise ValueError("an unavailable band carries only zero sentinels")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)
        object.__setattr__(self, "uncertainty_alpha", alpha)

    @property
    def ready(self) -> bool:
        return self.status is BandStatus.READY

    @classmethod
    def unavailable(cls, status: BandStatus) -> "NumericBand":
        if status is BandStatus.READY:
            raise ValueError("a ready band needs values")
        return cls(0.0, 0.0, 0.0, 0.0, status)

    @classmethod
    def exact(cls, value: Real) -> "NumericBand":
        point = _finite(value, "exact band value")
        if point < 0.0:
            raise ValueError("exact band value must be non-negative")
        return cls(point, point, point, 0.0, BandStatus.READY)

    @classmethod
    def interval(
        cls,
        value: Real,
        lower: Real,
        upper: Real,
        uncertainty_alpha: Real,
    ) -> "NumericBand":
        return cls(
            _finite(value, "band value"),
            _finite(lower, "band lower"),
            _finite(upper, "band upper"),
            _finite(uncertainty_alpha, "band uncertainty_alpha"),
            BandStatus.READY,
        )

    def as_record(self) -> dict[str, object]:
        return {
            "value": self.value,
            "lower": self.lower,
            "upper": self.upper,
            "uncertainty_alpha": self.uncertainty_alpha,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class NumericIncidenceState:
    """The identity-free sufficient-statistic boundary for rarefaction.

    ``positions`` is ordered by a schema that remains private to credit
    assignment.  Each row is a :data:`PositionStatistics` tuple.  The second
    tuple contains only observed and failed unit counts; excluded units do not
    cross the estimator boundary.
    """

    positions: tuple[PositionStatistics, ...]
    admission_counts: AdmissionStatistics

    def __post_init__(self) -> None:
        if not isinstance(self.positions, tuple) or not self.positions:
            raise ValueError("positions must be a non-empty tuple")
        normalized: list[PositionStatistics] = []
        for index, row in enumerate(self.positions):
            if not isinstance(row, tuple) or len(row) != POSITION_STATISTIC_WIDTH:
                raise ValueError(
                    f"position {index} must be a {POSITION_STATISTIC_WIDTH}-item tuple"
                )
            accepted = _non_negative_integer(
                row[POSITION_ACCEPTED_DISTINCT],
                f"positions[{index}].accepted_distinct",
            )
            samples = _non_negative_integer(
                row[POSITION_OBSERVED_SAMPLES],
                f"positions[{index}].observed_samples",
            )
            frequencies = row[POSITION_FREQUENCY_OF_FREQUENCIES]
            if not isinstance(frequencies, tuple) or len(frequencies) != samples + 1:
                raise ValueError(
                    "frequency-of-frequencies must contain indices zero through "
                    "observed_samples"
                )
            frequencies = tuple(
                _non_negative_integer(value, f"positions[{index}].frequency[{rank}]")
                for rank, value in enumerate(frequencies)
            )
            if sum(frequencies) != accepted:
                raise ValueError(
                    "frequency-of-frequencies must partition accepted identities"
                )
            normalized.append((accepted, samples, frequencies))
        if (
            not isinstance(self.admission_counts, tuple)
            or len(self.admission_counts) != ADMISSION_STATISTIC_WIDTH
        ):
            raise ValueError(
                f"admission_counts must be a {ADMISSION_STATISTIC_WIDTH}-item tuple"
            )
        admission = tuple(
            _non_negative_integer(value, f"admission_counts[{index}]")
            for index, value in enumerate(self.admission_counts)
        )
        observed = admission[ADMISSION_OBSERVED]
        if any(row[POSITION_OBSERVED_SAMPLES] != observed for row in normalized):
            raise ValueError(
                "every position's observed_samples must equal admission observed"
            )
        object.__setattr__(self, "positions", tuple(normalized))
        object.__setattr__(self, "admission_counts", admission)

    @property
    def width(self) -> int:
        return len(self.positions)

    def as_record(self) -> dict[str, object]:
        return {
            "positions": [
                [accepted, samples, list(frequencies)]
                for accepted, samples, frequencies in self.positions
            ],
            "admission_counts": list(self.admission_counts),
        }

    @classmethod
    def from_record(cls, value: object) -> "NumericIncidenceState":
        if not isinstance(value, Mapping) or set(value) != {"positions", "admission_counts"}:
            raise ValueError("numeric incidence record has invalid fields")
        positions = _record_array(value["positions"], "positions")
        rows = []
        for position in positions:
            row = _record_array(position, "position")
            if len(row) != POSITION_STATISTIC_WIDTH:
                raise ValueError("numeric incidence position has invalid width")
            rows.append((row[0], row[1], _record_array(row[2], "frequencies")))
        return cls(tuple(rows), _record_array(value["admission_counts"], "admission counts"))


@dataclass(frozen=True)
class NumericYieldProjection:
    """Rarefaction output aligned only by numeric vector position."""

    source_state: NumericIncidenceState
    expected_totals: tuple[NumericBand, ...]
    expected_next_yields: tuple[NumericBand, ...]
    conditional_next_yields: tuple[NumericBand, ...]
    usable_observation_probability: NumericBand
    joint_uncertainty_alpha: float

    def __post_init__(self) -> None:
        if not isinstance(self.source_state, NumericIncidenceState):
            raise TypeError("source_state must be a NumericIncidenceState")
        widths = {
            len(self.expected_totals),
            len(self.expected_next_yields),
            len(self.conditional_next_yields),
        }
        if len(widths) != 1 or next(iter(widths), 0) == 0:
            raise ValueError("projection tuples must have one common non-zero width")
        for name in (
            "expected_totals",
            "expected_next_yields",
            "conditional_next_yields",
        ):
            if not isinstance(getattr(self, name), tuple) or any(
                not isinstance(band, NumericBand) for band in getattr(self, name)
            ):
                raise TypeError(f"{name} must be a tuple of NumericBand values")
        if not isinstance(self.usable_observation_probability, NumericBand):
            raise TypeError("usable_observation_probability must be a NumericBand")
        if self.source_state.width != self.width:
            raise ValueError("source state and projection widths differ")
        alpha = _finite(self.joint_uncertainty_alpha, "joint_uncertainty_alpha")
        if not 0.0 < alpha < 1.0:
            raise ValueError("joint_uncertainty_alpha must satisfy 0 < alpha < 1")
        object.__setattr__(self, "joint_uncertainty_alpha", alpha)

    @property
    def width(self) -> int:
        return len(self.expected_totals)

    def as_record(self) -> dict[str, object]:
        return {
            "source_state": self.source_state.as_record(),
            "expected_totals": [band.as_record() for band in self.expected_totals],
            "expected_next_yields": [
                band.as_record() for band in self.expected_next_yields
            ],
            "conditional_next_yields": [
                band.as_record() for band in self.conditional_next_yields
            ],
            "usable_observation_probability": (
                self.usable_observation_probability.as_record()
            ),
            "joint_uncertainty_alpha": self.joint_uncertainty_alpha,
        }


@dataclass(frozen=True)
class ResultColumnSchema:
    """Credit assignment's frozen mapping from result columns to positions."""

    columns: tuple[str, ...]
    reference_point: tuple[float, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.columns, tuple) or not self.columns:
            raise ValueError("columns must be a non-empty tuple")
        columns = tuple(
            _stable_id(value, "result column") for value in self.columns
        )
        if len(set(columns)) != len(columns):
            raise ValueError("result columns must be unique")
        if not isinstance(self.reference_point, tuple):
            raise ValueError("reference_point must be a tuple")
        reference = tuple(
            _probability(value, f"reference_point[{index}]")
            for index, value in enumerate(self.reference_point)
        )
        if len(reference) != len(columns):
            raise ValueError("reference_point must have one coordinate per column")
        if any(value != 0.0 for value in reference):
            raise ValueError("marginal dominated hypervolume requires explicit zero")
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "reference_point", reference)

    @property
    def width(self) -> int:
        return len(self.columns)

    def as_record(self) -> dict[str, object]:
        return {
            "columns": list(self.columns),
            "reference_point": list(self.reference_point),
        }


@dataclass(frozen=True)
class CreditObservation(ClosedRecord):
    """Accepted identities from one unit, partitioned by result column."""

    accepted: Mapping[str, tuple[str, ...]]
    status: AdmissionStatus
    code: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, AdmissionStatus):
            raise ValueError("status must be an AdmissionStatus")
        if not isinstance(self.accepted, Mapping):
            raise ValueError("accepted must map result columns to identities")
        frozen = {
            _stable_id(column, "result column"): _identities(
                values,
                "result identity",
            )
            for column, values in self.accepted.items()
        }
        if not isinstance(self.code, str) or not _CLOSED_TOKEN.fullmatch(self.code):
            raise ValueError("credit observation code must be a closed token")
        object.__setattr__(self, "accepted", MappingProxyType(frozen))

    @classmethod
    def observed(
        cls,
        accepted: Mapping[str, Iterable[str]],
        *,
        code: str = "observed",
    ) -> "CreditObservation":
        return cls(
            accepted={column: tuple(values) for column, values in accepted.items()},
            status=OBSERVED,
            code=code,
        )

    @classmethod
    def failed(
        cls,
        accepted: Mapping[str, Iterable[str]],
        *,
        code: str,
    ) -> "CreditObservation":
        return cls(
            accepted={column: tuple(values) for column, values in accepted.items()},
            status=FAILED,
            code=code,
        )

    @classmethod
    def excluded(
        cls,
        accepted: Mapping[str, Iterable[str]],
        *,
        code: str,
    ) -> "CreditObservation":
        return cls(
            accepted={column: tuple(values) for column, values in accepted.items()},
            status=EXCLUDED,
            code=code,
        )

    def as_record(self) -> dict[str, object]:
        return {
            "accepted": {
                column: list(values) for column, values in self.accepted.items()
            },
            "status": self.status.value,
            "code": self.code,
        }


@dataclass(frozen=True)
class CreditSnapshot:
    accepted_by_position: tuple[tuple[str, ...], ...]
    incidence_by_position: tuple[tuple[tuple[str, int], ...], ...]
    numeric_state: NumericIncidenceState
    excluded_units: int

    def __post_init__(self) -> None:
        if not isinstance(self.numeric_state, NumericIncidenceState):
            raise TypeError("numeric_state must be a NumericIncidenceState")
        if not isinstance(self.accepted_by_position, tuple) or any(
            not isinstance(position, tuple) for position in self.accepted_by_position
        ):
            raise TypeError("accepted_by_position must be a tuple of tuples")
        if len(self.accepted_by_position) != self.numeric_state.width:
            raise ValueError("accepted identities and numeric state widths differ")
        if (
            not isinstance(self.incidence_by_position, tuple)
            or len(self.incidence_by_position) != self.numeric_state.width
        ):
            raise ValueError("incidence history must have one row per position")
        observed = self.numeric_state.admission_counts[ADMISSION_OBSERVED]
        owners: set[str] = set()
        for index, incidence in enumerate(self.incidence_by_position):
            if not isinstance(incidence, tuple):
                raise TypeError("incidence history rows must be tuples")
            accepted = self.accepted_by_position[index]
            if _identities(accepted, "accepted identity") != accepted:
                raise ValueError("accepted identity rows must be unique and ordered")
            overlap = owners.intersection(accepted)
            if overlap:
                raise ValueError(
                    f"accepted identities occupy multiple positions: {sorted(overlap)}"
                )
            owners.update(accepted)
            if tuple(identity for identity, _ in incidence) != accepted:
                raise ValueError(
                    "incidence history must preserve every accepted identity in order"
                )
            derived_frequencies = [0] * (observed + 1)
            for identity, frequency in incidence:
                _stable_id(identity, "incidence identity")
                value = _non_negative_integer(frequency, "incidence frequency")
                if value > observed:
                    raise ValueError(
                        "identity incidence cannot exceed observed unit count"
                    )
                derived_frequencies[value] += 1
            numeric_row = self.numeric_state.positions[index]
            if numeric_row[POSITION_ACCEPTED_DISTINCT] != len(accepted) or numeric_row[
                POSITION_FREQUENCY_OF_FREQUENCIES
            ] != tuple(derived_frequencies):
                raise ValueError(
                    "identity incidence history disagrees with numeric statistics"
                )
        _non_negative_integer(self.excluded_units, "excluded_units")

    @property
    def accepted_counts(self) -> tuple[int, ...]:
        return tuple(len(position) for position in self.accepted_by_position)

    def as_record(self) -> dict[str, object]:
        return {
            "accepted_by_position": [
                list(position) for position in self.accepted_by_position
            ],
            "incidence_by_position": [
                [[identity, frequency] for identity, frequency in position]
                for position in self.incidence_by_position
            ],
            "numeric_state": self.numeric_state.as_record(),
            "excluded_units": self.excluded_units,
        }

    @classmethod
    def from_record(cls, value: object) -> "CreditSnapshot":
        fields = {"accepted_by_position", "incidence_by_position", "numeric_state", "excluded_units"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("credit snapshot has invalid fields")
        return cls(
            tuple(_record_array(row, "accepted identities") for row in _record_array(value["accepted_by_position"], "accepted positions")),
            tuple(tuple(_record_array(pair, "identity frequency") for pair in _record_array(row, "incidence identities")) for row in _record_array(value["incidence_by_position"], "incidence positions")),
            NumericIncidenceState.from_record(value["numeric_state"]),
            value["excluded_units"],
        )


def _record_array(value, name):
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    return tuple(value)


@dataclass(frozen=True)
class CreditAdmission:
    before: CreditSnapshot
    after: CreditSnapshot
    status: AdmissionStatus
    new_identity_ids: tuple[str, ...]

    @property
    def counts_toward_decision(self) -> bool:
        return self.status is not EXCLUDED

    def as_record(self) -> dict[str, object]:
        return {
            "before": self.before.as_record(),
            "after": self.after.as_record(),
            "status": self.status.value,
            "new_identity_ids": list(self.new_identity_ids),
            "counts_toward_decision": self.counts_toward_decision,
        }


@dataclass(frozen=True)
class HypervolumeCredit:
    actual: NumericBand
    projected_next: NumericBand
    normalization: tuple[float, ...]
    before_progress: tuple[float, ...]
    after_progress: tuple[float, ...]
    projected_progress: tuple[float, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.actual, NumericBand) or not isinstance(
            self.projected_next, NumericBand
        ):
            raise TypeError("credit values must be NumericBand values")
        widths = {
            len(self.normalization),
            len(self.before_progress),
            len(self.after_progress),
            len(self.projected_progress),
        }
        if len(widths) != 1:
            raise ValueError("credit vectors must have one common width")
        for value in self.normalization:
            if _finite(value, "normalization") < 1.0:
                raise ValueError("normalization coordinates must be at least one")
        for name in ("before_progress", "after_progress", "projected_progress"):
            for value in getattr(self, name):
                _probability(value, name)

    @classmethod
    def unavailable(
        cls,
        width: int,
        status: BandStatus,
    ) -> "HypervolumeCredit":
        return cls(
            actual=NumericBand.unavailable(status),
            projected_next=NumericBand.unavailable(status),
            normalization=tuple(1.0 for _ in range(width)),
            before_progress=tuple(0.0 for _ in range(width)),
            after_progress=tuple(0.0 for _ in range(width)),
            projected_progress=tuple(0.0 for _ in range(width)),
        )

    def as_record(self) -> dict[str, object]:
        return {
            "actual": self.actual.as_record(),
            "projected_next": self.projected_next.as_record(),
            "normalization": list(self.normalization),
            "before_progress": list(self.before_progress),
            "after_progress": list(self.after_progress),
            "projected_progress": list(self.projected_progress),
        }


def dominated_hypervolume(
    progress: Sequence[Real],
    reference_point: Sequence[Real],
) -> float:
    """Return one vector's dominated volume against an explicit zero point."""

    values = tuple(
        _probability(value, f"progress[{index}]")
        for index, value in enumerate(progress)
    )
    reference = tuple(
        _probability(value, f"reference_point[{index}]")
        for index, value in enumerate(reference_point)
    )
    if not values or len(values) != len(reference):
        raise ValueError("progress and reference_point need the same non-zero width")
    if any(value != 0.0 for value in reference):
        raise ValueError("dominated hypervolume requires explicit zero reference")
    return math.prod(values)


def marginal_dominated_hypervolume(
    before: Sequence[Real],
    after: Sequence[Real],
    reference_point: Sequence[Real],
) -> float:
    """Return exact marginal dominated volume with no epsilon relaxation."""

    before_values = tuple(
        _probability(value, f"before[{index}]")
        for index, value in enumerate(before)
    )
    after_values = tuple(
        _probability(value, f"after[{index}]")
        for index, value in enumerate(after)
    )
    if len(before_values) != len(after_values):
        raise ValueError("before and after vectors must have the same width")
    if any(after_values[index] < before_values[index] for index in range(len(before_values))):
        raise ValueError("normalized progress cannot decrease")
    return dominated_hypervolume(
        after_values, reference_point
    ) - dominated_hypervolume(before_values, reference_point)


def _unavailable_status(bands: Iterable[NumericBand]) -> BandStatus:
    statuses = tuple(band.status for band in bands if not band.ready)
    if BandStatus.UNIDENTIFIABLE in statuses:
        return BandStatus.UNIDENTIFIABLE
    return BandStatus.INSUFFICIENT


class MarginalHypervolumeAssignment:
    """Own identities, emit sufficient statistics, and assign method credit."""

    def __init__(self, schema: ResultColumnSchema) -> None:
        if not isinstance(schema, ResultColumnSchema):
            raise TypeError("schema must be a ResultColumnSchema")
        self.schema = schema
        self._accepted: list[dict[str, None]] = [
            {} for _ in range(schema.width)
        ]
        self._incidence: list[Counter[str]] = [
            Counter() for _ in range(schema.width)
        ]
        self._identity_owner: dict[str, int] = {}
        self._observed_units = 0
        self._failed_units = 0
        self._excluded_units = 0

    def _snapshot(self) -> CreditSnapshot:
        rows: list[PositionStatistics] = []
        for accepted, incidence in zip(self._accepted, self._incidence):
            frequencies = [0] * (self._observed_units + 1)
            for identity in accepted:
                frequency = incidence.get(identity, 0)
                if frequency > self._observed_units:
                    raise RuntimeError("incidence frequency exceeds observed samples")
                frequencies[frequency] += 1
            rows.append(
                (
                    len(accepted),
                    self._observed_units,
                    tuple(frequencies),
                )
            )
        return CreditSnapshot(
            accepted_by_position=tuple(
                tuple(position) for position in self._accepted
            ),
            incidence_by_position=tuple(
                tuple(
                    (identity, self._incidence[index].get(identity, 0))
                    for identity in accepted
                )
                for index, accepted in enumerate(self._accepted)
            ),
            numeric_state=NumericIncidenceState(
                positions=tuple(rows),
                admission_counts=(self._observed_units, self._failed_units),
            ),
            excluded_units=self._excluded_units,
        )

    def state(self) -> CreditSnapshot:
        return self._snapshot()

    @classmethod
    def from_snapshot(
        cls,
        schema: ResultColumnSchema,
        snapshot: CreditSnapshot,
    ) -> "MarginalHypervolumeAssignment":
        """Restore the identity buckets needed for the next exact update."""

        if not isinstance(snapshot, CreditSnapshot):
            raise TypeError("snapshot must be a CreditSnapshot")
        if snapshot.numeric_state.width != schema.width:
            raise ValueError("snapshot width differs from the result schema")
        assignment = cls(schema)
        for position, accepted in enumerate(snapshot.accepted_by_position):
            for identity in accepted:
                if identity in assignment._identity_owner:
                    raise ValueError(
                        f"accepted identity {identity!r} occupies multiple positions"
                    )
                assignment._accepted[position][identity] = None
                assignment._identity_owner[identity] = position
            assignment._incidence[position].update(
                dict(snapshot.incidence_by_position[position])
            )
        assignment._observed_units = snapshot.numeric_state.admission_counts[
            ADMISSION_OBSERVED
        ]
        assignment._failed_units = snapshot.numeric_state.admission_counts[
            ADMISSION_FAILED
        ]
        assignment._excluded_units = snapshot.excluded_units
        if assignment._snapshot() != snapshot:
            raise ValueError("snapshot incidence history is internally inconsistent")
        return assignment

    def admit(self, observation: CreditObservation) -> CreditAdmission:
        if not isinstance(observation, CreditObservation):
            raise TypeError("credit assignment requires a CreditObservation")
        expected = set(self.schema.columns)
        actual = set(observation.accepted)
        if actual != expected:
            raise ValueError(
                "accepted results must name every declared result column: "
                f"missing {sorted(expected - actual)}, "
                f"undeclared {sorted(actual - expected)}"
            )
        positioned = tuple(
            observation.accepted[column] for column in self.schema.columns
        )
        pending_owner = dict(self._identity_owner)
        for position, identities in enumerate(positioned):
            for identity in identities:
                owner = pending_owner.get(identity)
                if owner is not None and owner != position:
                    raise ValueError(
                        f"accepted identity {identity!r} moved between result columns"
                    )
                pending_owner[identity] = position

        before = self._snapshot()
        new: list[str] = []
        for position, identities in enumerate(positioned):
            for identity in identities:
                if identity not in self._accepted[position]:
                    self._accepted[position][identity] = None
                    self._identity_owner[identity] = position
                    new.append(identity)
                if observation.status is OBSERVED:
                    self._incidence[position][identity] += 1
        if observation.status is OBSERVED:
            self._observed_units += 1
        elif observation.status is FAILED:
            self._failed_units += 1
        else:
            self._excluded_units += 1
        after = self._snapshot()
        return CreditAdmission(
            before=before,
            after=after,
            status=observation.status,
            new_identity_ids=tuple(new),
        )

    def assign(
        self,
        admission: CreditAdmission,
        before_projection: NumericYieldProjection,
        after_projection: NumericYieldProjection,
    ) -> HypervolumeCredit:
        if not isinstance(admission, CreditAdmission):
            raise TypeError("admission must be a CreditAdmission")
        if not isinstance(before_projection, NumericYieldProjection) or not isinstance(
            after_projection, NumericYieldProjection
        ):
            raise TypeError("before_projection and after_projection must be numeric")
        if (
            before_projection.width != self.schema.width
            or after_projection.width != self.schema.width
        ):
            raise ValueError("projection width differs from the result schema")
        if before_projection.source_state != admission.before.numeric_state:
            raise ValueError("before projection does not match admission state")
        if after_projection.source_state != admission.after.numeric_state:
            raise ValueError("after projection does not match admission state")

        after_bands = (
            after_projection.expected_totals
            + after_projection.expected_next_yields
        )
        before_totals = before_projection.expected_totals

        before_counts = admission.before.accepted_counts
        after_counts = admission.after.accepted_counts
        if any(not band.ready for band in before_totals):
            actual = NumericBand.unavailable(_unavailable_status(before_totals))
            normalization = tuple(1.0 for _ in range(self.schema.width))
            before_progress = tuple(0.0 for _ in range(self.schema.width))
            after_progress = tuple(0.0 for _ in range(self.schema.width))
        else:
            # Realized unit credit freezes the pre-unit fitted scale.  The
            # post-unit distinct count is only a lower floor on that scale.
            normalization = tuple(
                max(1.0, before_totals[index].value, after_counts[index])
                for index in range(self.schema.width)
            )
            before_progress_values: list[float] = []
            after_progress_values: list[float] = []
            for index in range(self.schema.width):
                exact_empty = (
                    before_counts[index] == 0
                    and after_counts[index] == 0
                    and before_totals[index].upper == 0.0
                    and before_projection.expected_next_yields[index].ready
                    and before_projection.expected_next_yields[index].upper == 0.0
                )
                before_progress_values.append(
                    1.0
                    if exact_empty
                    else before_counts[index] / normalization[index]
                )
                after_progress_values.append(
                    1.0
                    if exact_empty
                    else after_counts[index] / normalization[index]
                )
            before_progress = tuple(before_progress_values)
            after_progress = tuple(after_progress_values)
            actual = NumericBand.exact(
                marginal_dominated_hypervolume(
                    before_progress,
                    after_progress,
                    self.schema.reference_point,
                )
            )

        if any(not band.ready for band in after_bands):
            unavailable = NumericBand.unavailable(
                _unavailable_status(after_bands)
            )
            return HypervolumeCredit(
                actual=actual,
                projected_next=unavailable,
                normalization=normalization,
                before_progress=before_progress,
                after_progress=after_progress,
                projected_progress=after_progress,
            )

        point_current: list[float] = []
        point_projected: list[float] = []
        current_lower: list[float] = []
        current_upper: list[float] = []
        projected_lower: list[float] = []
        projected_upper: list[float] = []
        for index in range(self.schema.width):
            count = float(after_counts[index])
            total = after_projection.expected_totals[index]
            next_yield = after_projection.expected_next_yields[index]

            def coordinates(total_value: float, next_value: float) -> tuple[float, float]:
                if (
                    count == 0.0
                    and total.upper == 0.0
                    and next_yield.upper == 0.0
                ):
                    return 1.0, 1.0
                scale = max(1.0, total_value, count + 1.0)
                return count / scale, min(1.0, (count + next_value) / scale)

            current, projected = coordinates(total.value, next_yield.value)
            point_current.append(current)
            point_projected.append(projected)
            if (
                count == 0.0
                and total.upper == 0.0
                and next_yield.upper == 0.0
            ):
                current_lower.append(1.0)
                current_upper.append(1.0)
                projected_lower.append(1.0)
                projected_upper.append(1.0)
            else:
                current_lower.append(
                    count / max(1.0, total.upper, count + 1.0)
                )
                current_upper.append(
                    count / max(1.0, total.lower, count + 1.0)
                )
                projected_lower.append(
                    min(
                        1.0,
                        (count + next_yield.lower)
                        / max(1.0, total.upper, count + 1.0),
                    )
                )
                projected_upper.append(
                    min(
                        1.0,
                        (count + next_yield.upper)
                        / max(1.0, total.lower, count + 1.0),
                    )
                )

        point_credit = marginal_dominated_hypervolume(
            point_current,
            point_projected,
            self.schema.reference_point,
        )
        lower_credit = max(
            0.0,
            dominated_hypervolume(projected_lower, self.schema.reference_point)
            - dominated_hypervolume(current_upper, self.schema.reference_point),
        )
        upper_credit = max(
            0.0,
            dominated_hypervolume(projected_upper, self.schema.reference_point)
            - dominated_hypervolume(current_lower, self.schema.reference_point),
        )
        lower_credit = min(lower_credit, point_credit)
        upper_credit = min(1.0, max(upper_credit, point_credit))
        alpha = after_projection.joint_uncertainty_alpha
        projected_band = (
            NumericBand.exact(point_credit)
            if lower_credit == point_credit == upper_credit
            else NumericBand.interval(
                point_credit,
                lower_credit,
                upper_credit,
                alpha,
            )
        )
        return HypervolumeCredit(
            actual=actual,
            projected_next=projected_band,
            normalization=normalization,
            before_progress=before_progress,
            after_progress=after_progress,
            projected_progress=tuple(point_projected),
        )


def open_marginal_dominated_hypervolume(
    schema: ResultColumnSchema,
    parameters: Mapping[str, object],
) -> MarginalHypervolumeAssignment:
    """Open one credit assignment; this function has no tunable parameters."""

    if not isinstance(parameters, Mapping) or parameters:
        raise ValueError(
            "marginal_dominated_hypervolume parameters must be an empty object"
        )
    return MarginalHypervolumeAssignment(schema)


credit_function_library = FunctionLibrary()
MARGINAL_DOMINATED_HYPERVOLUME = credit_function_library.register(
    LibraryFunction(
        library="credit_assignment",
        function_id="marginal_dominated_hypervolume",
        interface="credit.numeric_incidence_hypervolume",
        description=(
            "Admit accepted identities by declared result column, emit positional "
            "incidence sufficient statistics, and assign exact/projected marginal "
            "zero-reference dominated hypervolume."
        ),
        implementation=FunctionImplementation(
            module="numeric_control_library.credit_assignment",
            symbol="open_marginal_dominated_hypervolume",
            is_async=False,
        ),
        input_type="ResultColumnSchema plus empty parameter object",
        output_type="MarginalHypervolumeAssignment",
        effect="Retains accepted identities and full-history incidence counts per scope.",
        failure_contract=(
            "Rejects undeclared columns, cross-column identity movement, non-finite "
            "numbers, non-zero references, and malformed positional projections."
        ),
        provenance={
            "parameter_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "credit": "marginal dominated hypervolume",
            "reference_point": "explicit zero vector",
        },
    )
)


__all__ = [
    "ADMISSION_FAILED",
    "ADMISSION_OBSERVED",
    "ADMISSION_STATISTIC_WIDTH",
    "EXCLUDED",
    "FAILED",
    "MARGINAL_DOMINATED_HYPERVOLUME",
    "OBSERVED",
    "POSITION_ACCEPTED_DISTINCT",
    "POSITION_FREQUENCY_OF_FREQUENCIES",
    "POSITION_OBSERVED_SAMPLES",
    "POSITION_STATISTIC_WIDTH",
    "AdmissionStatistics",
    "AdmissionStatus",
    "BandStatus",
    "CreditAdmission",
    "CreditObservation",
    "CreditSnapshot",
    "HypervolumeCredit",
    "MarginalHypervolumeAssignment",
    "NumericBand",
    "NumericIncidenceState",
    "NumericYieldProjection",
    "PositionStatistics",
    "ResultColumnSchema",
    "credit_function_library",
    "dominated_hypervolume",
    "marginal_dominated_hypervolume",
    "open_marginal_dominated_hypervolume",
]
