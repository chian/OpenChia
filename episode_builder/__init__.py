"""Materialization contracts and immutable storage for EpisodeBuilder."""

from ._contract_base import (
    BuildAttempt,
    BuildDeficit,
    BuildReceipt,
    EmittedEpisodeModule,
    MaterializerIdentity,
)
from ._contract_chain import (
    ApprovedBuildRequest,
    BuildAdmissionReport,
    BuildManifest,
    WorkflowMaterializationPlan,
)
from ._contract_plan import (
    EdgeMaterializationPlan,
    NodeMaterializationPlan,
)
from .inspection import (
    EpisodeSpecification,
    MaterializationInspectionInput,
    MaterializedSpecification,
    ProjectedDeficit,
    SourceSymbolIndexEntry,
    SpecificationPart,
    project_materialized_specification,
)
from .store import (
    BuildArtifactConflictError,
    BuildArtifactNotFoundError,
    BuildStore,
    BuildStoreCorruptionError,
    BuildStoreError,
)
from .service import CancellationSignal, EpisodeBuilder, ProgressCallback


__all__ = [
    "ApprovedBuildRequest",
    "BuildAdmissionReport",
    "BuildArtifactConflictError",
    "BuildArtifactNotFoundError",
    "BuildAttempt",
    "BuildDeficit",
    "BuildManifest",
    "BuildReceipt",
    "BuildStore",
    "BuildStoreCorruptionError",
    "BuildStoreError",
    "CancellationSignal",
    "EdgeMaterializationPlan",
    "EmittedEpisodeModule",
    "EpisodeSpecification",
    "EpisodeBuilder",
    "MaterializationInspectionInput",
    "MaterializedSpecification",
    "MaterializerIdentity",
    "NodeMaterializationPlan",
    "ProgressCallback",
    "ProjectedDeficit",
    "SourceSymbolIndexEntry",
    "SpecificationPart",
    "WorkflowMaterializationPlan",
    "project_materialized_specification",
]
