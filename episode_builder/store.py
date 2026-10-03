"""Atomic content-addressed persistence for EpisodeBuilder artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import threading
from typing import TYPE_CHECKING, Any, Callable, Mapping, TypeVar

from agent.duet_contracts import canonical_json
from agent.episode_contracts import OpaqueId, Sha256Digest

from ._contract_base import (
    BuildAttempt,
    BuildReceipt,
    EmittedEpisodeModule,
)
from ._contract_chain import (
    ApprovedBuildRequest,
    BuildAdmissionReport,
    BuildManifest,
    WorkflowMaterializationPlan,
    is_implementation_directive_target,
)

if TYPE_CHECKING:
    from .inspection import (
        MaterializationInspectionInput,
        MaterializedSpecification,
    )


class BuildStoreError(RuntimeError):
    """Base class for immutable build-store failures."""


class BuildArtifactNotFoundError(BuildStoreError):
    """A requested content-addressed artifact is absent."""


class BuildArtifactConflictError(BuildStoreError):
    """An existing content address contains different bytes."""


class BuildStoreCorruptionError(BuildStoreError):
    """Persisted bytes fail canonical or typed identity validation."""


_Record = TypeVar("_Record")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return canonical_json(value).encode("utf-8")


class BuildStore:
    """Immutable records and module blobs rooted at ``root/builds``.

    A complete temporary file is atomically linked into its content address.
    An existing address is accepted only when its bytes are identical; no
    latest pointer or other mutable index is maintained.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.builds_root = self.root / "builds"
        self._records_root = self.builds_root / "records"
        self._objects_root = self.builds_root / "objects" / "sha256"
        self._packages_root = self.builds_root / "source_packages"
        self._lock = threading.RLock()
        for path in (
            self._records_root / "requests",
            self._records_root / "attempts",
            self._records_root / "attempt_claims",
            self._records_root / "plans",
            self._records_root / "modules",
            self._records_root / "admission_reports",
            self._records_root / "manifests",
            self._records_root / "receipts",
            self._records_root / "model_calls",
            self._records_root / "materialization_handoffs",
            self._objects_root,
            self._packages_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _id_value(value: OpaqueId | str, name: str) -> str:
        if isinstance(value, OpaqueId):
            return value.value
        if isinstance(value, str):
            return OpaqueId(value).value
        raise TypeError(f"{name} must be an OpaqueId or opaque ID string")

    def _record_path(
        self,
        category: str,
        identifier: OpaqueId | str,
    ) -> Path:
        return self._records_root / category / f"{self._id_value(identifier, category)}.json"

    def _publish(self, path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if path.exists():
                if path.read_bytes() != payload:
                    raise BuildArtifactConflictError(
                        f"content address already contains different bytes: {path.name}"
                    )
                return
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".pending-",
                dir=path.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    if path.read_bytes() != payload:
                        raise BuildArtifactConflictError(
                            "a concurrent writer published different bytes at "
                            f"{path.name}"
                        )
            finally:
                temporary.unlink(missing_ok=True)

    def _put_record(
        self,
        category: str,
        identifier: OpaqueId,
        value: Mapping[str, Any],
    ) -> OpaqueId:
        self._publish(
            self._record_path(category, identifier),
            _canonical_bytes(value),
        )
        return identifier

    def _read_record(
        self,
        category: str,
        identifier: OpaqueId | str,
        loader: Callable[[object], _Record],
    ) -> _Record:
        path = self._record_path(category, identifier)
        try:
            payload = path.read_bytes()
        except FileNotFoundError as exc:
            raise BuildArtifactNotFoundError(
                f"unknown {category.rstrip('s')} artifact {path.stem!r}"
            ) from exc
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BuildStoreCorruptionError(
                f"stored artifact {path.name!r} is not valid JSON"
            ) from exc
        if not isinstance(value, Mapping) or _canonical_bytes(value) != payload:
            raise BuildStoreCorruptionError(
                f"stored artifact {path.name!r} is not canonical"
            )
        try:
            result = loader(value)
        except (TypeError, ValueError) as exc:
            raise BuildStoreCorruptionError(
                f"stored artifact {path.name!r} failed typed validation"
            ) from exc
        return result

    def put_build_request(self, value: ApprovedBuildRequest) -> OpaqueId:
        if not isinstance(value, ApprovedBuildRequest):
            raise TypeError("value must be an ApprovedBuildRequest")
        if value.predecessor_receipt is not None:
            stored_receipt = self.read_receipt(
                value.predecessor_receipt.receipt_id
            )
            if stored_receipt.as_record() != value.predecessor_receipt.as_record():
                raise ValueError(
                    "approved request predecessor receipt differs from the store"
                )
            predecessor_request = self.read_build_request(
                stored_receipt.build_request_id
            )
            baseline = value.refinement_baseline
            if baseline is None or (
                baseline.duet_id
                != predecessor_request.frozen_workflow.duet_id
                or baseline.authority_head_approval_id
                != predecessor_request.authority_approval.approval_id
                or baseline.workflow_approval_id
                != predecessor_request.workflow_approval.approval_id
                or baseline.frozen_workflow_artifact_id
                != predecessor_request.frozen_workflow.artifact_id
                or baseline.workflow_hash
                != predecessor_request.frozen_workflow.workflow_hash
            ):
                raise ValueError(
                    "approved request baseline authority differs from its "
                    "predecessor request"
                )
            stored_manifest = None
            if value.predecessor_manifest is not None:
                stored_manifest = self.read_manifest(
                    value.predecessor_manifest.manifest_id
                )
                if stored_manifest.as_record() != value.predecessor_manifest.as_record():
                    raise ValueError(
                        "approved request predecessor manifest differs from the store"
                    )
            projection = self.project_receipt(
                stored_receipt.receipt_id,
                verify_source_package=False,
            )
            if (
                projection.specification_id
                != baseline.materialized_specification_id
                or projection.content_hash
                != baseline.materialized_specification_hash
            ):
                raise ValueError(
                    "approved request baseline differs from the predecessor "
                    "Materialized Specification"
                )
            stable_targets = set(projection.stable_targets)
            proposal = value.refinement_proposal
            if proposal is not None:
                directive_targets = [
                    item.target for item in proposal.implementation_directives
                ]
                note_targets = [
                    item.target
                    for item in value.refinement_notes
                    if item.target.layer.value
                    == "materialization_implementation"
                ]
                for target in (*directive_targets, *note_targets):
                    if target.json_pointer not in stable_targets:
                        raise ValueError(
                            "approved refinement target is absent from the "
                            "predecessor Materialized Specification"
                        )
                    if target.episode_local_id is not None:
                        prefix = (
                            "/episodes/"
                            + target.episode_local_id.replace("~", "~0").replace(
                                "/", "~1"
                            )
                        )
                        if not (
                            target.json_pointer == prefix
                            or target.json_pointer.startswith(f"{prefix}/")
                        ):
                            raise ValueError(
                                "refinement target Episode ID and pointer disagree"
                            )
                for target in directive_targets:
                    if not is_implementation_directive_target(target):
                        raise ValueError(
                            "implementation directive does not target an executable "
                            "Materialized Specification scope"
                        )
        return self._put_record(
            "requests",
            value.build_request_id,
            value.as_record(),
        )

    def read_build_request(
        self,
        build_request_id: OpaqueId | str,
    ) -> ApprovedBuildRequest:
        result = self._read_record(
            "requests",
            build_request_id,
            ApprovedBuildRequest.from_record,
        )
        if result.build_request_id.value != self._id_value(
            build_request_id,
            "build_request_id",
        ):
            raise BuildStoreCorruptionError(
                "build request filename does not match its content identity"
            )
        return result

    def put_build_attempt(self, value: BuildAttempt) -> OpaqueId:
        if not isinstance(value, BuildAttempt):
            raise TypeError("value must be a BuildAttempt")
        request = self.read_build_request(value.build_request_id)
        if request.build_request_id != value.build_request_id:
            raise ValueError("build attempt names another request")
        with self._lock:
            if self.attempts_for_build_request(value.build_request_id):
                raise BuildArtifactConflictError(
                    "an approved build request may be attempted only once; "
                    "mint a fresh request nonce"
                )
            claim_path = self._record_path(
                "attempt_claims",
                value.build_request_id,
            )
            if claim_path.exists():
                raise BuildArtifactConflictError(
                    "approved build request nonce has already been consumed"
                )
            self._publish(
                claim_path,
                _canonical_bytes(
                    {
                        "build_request_id": value.build_request_id.value,
                        "build_attempt_id": value.build_attempt_id.value,
                    }
                ),
            )
            return self._put_record(
                "attempts",
                value.build_attempt_id,
                value.as_record(),
            )

    def read_build_attempt(
        self,
        build_attempt_id: OpaqueId | str,
    ) -> BuildAttempt:
        result = self._read_record(
            "attempts",
            build_attempt_id,
            BuildAttempt.from_record,
        )
        if result.build_attempt_id.value != self._id_value(
            build_attempt_id,
            "build_attempt_id",
        ):
            raise BuildStoreCorruptionError(
                "build attempt filename does not match its content identity"
            )
        self.read_build_request(result.build_request_id)
        return result

    def put_plan(self, value: WorkflowMaterializationPlan) -> OpaqueId:
        if not isinstance(value, WorkflowMaterializationPlan):
            raise TypeError("value must be a WorkflowMaterializationPlan")
        build_request = self.read_build_request(value.build_request_id)
        build_attempt = self.read_build_attempt(value.build_attempt_id)
        value.validate_against(build_request, build_attempt)
        return self._put_record("plans", value.plan_id, value.as_record())

    def read_plan(
        self,
        plan_id: OpaqueId | str,
    ) -> WorkflowMaterializationPlan:
        result = self._read_record(
            "plans",
            plan_id,
            WorkflowMaterializationPlan.from_record,
        )
        if result.plan_id.value != self._id_value(plan_id, "plan_id"):
            raise BuildStoreCorruptionError(
                "plan filename does not match its content identity"
            )
        return result

    def put_blob(self, payload: bytes) -> Sha256Digest:
        if not isinstance(payload, bytes):
            raise TypeError("build-store blobs must be bytes")
        digest = Sha256Digest.of_bytes(payload)
        self._publish(self._blob_path(digest), payload)
        return digest

    def _blob_path(self, digest: Sha256Digest | str) -> Path:
        value = digest if isinstance(digest, Sha256Digest) else Sha256Digest(digest)
        return self._objects_root / value.value.removeprefix("sha256:")

    def read_blob(self, digest: Sha256Digest | str) -> bytes:
        value = digest if isinstance(digest, Sha256Digest) else Sha256Digest(digest)
        path = self._blob_path(value)
        try:
            payload = path.read_bytes()
        except FileNotFoundError as exc:
            raise BuildArtifactNotFoundError(
                f"unknown build blob {value.value!r}"
            ) from exc
        if Sha256Digest.of_bytes(payload) != value:
            raise BuildStoreCorruptionError(
                f"build blob {value.value!r} does not match its digest"
            )
        return payload

    def put_emitted_module(self, value: EmittedEpisodeModule) -> OpaqueId:
        if not isinstance(value, EmittedEpisodeModule):
            raise TypeError("value must be an EmittedEpisodeModule")
        digest = self.put_blob(value.module_source.encode("utf-8"))
        if digest != value.source_hash:
            raise ValueError("emitted module source hash differs from its bytes")
        return self._put_record(
            "modules",
            value.emitted_module_id,
            value.as_record(),
        )

    def read_emitted_module(
        self,
        emitted_module_id: OpaqueId | str,
    ) -> EmittedEpisodeModule:
        result = self._read_record(
            "modules",
            emitted_module_id,
            EmittedEpisodeModule.from_record,
        )
        if result.emitted_module_id.value != self._id_value(
            emitted_module_id,
            "emitted_module_id",
        ):
            raise BuildStoreCorruptionError(
                "emitted-module filename does not match its content identity"
            )
        if self.read_blob(result.source_hash) != result.module_source.encode("utf-8"):
            raise BuildStoreCorruptionError(
                "emitted-module record differs from its source blob"
            )
        return result

    def put_admission_report(self, value: BuildAdmissionReport) -> OpaqueId:
        if not isinstance(value, BuildAdmissionReport):
            raise TypeError("value must be a BuildAdmissionReport")
        plan = self.read_plan(value.plan_id)
        value.validate_against(plan)
        if (
            value.build_request_id != plan.build_request_id
            or value.build_attempt_id != plan.build_attempt_id
        ):
            raise ValueError("admission report names another request or attempt")
        for digest in value.module_source_hashes.values():
            self.read_blob(digest)
        return self._put_record(
            "admission_reports",
            value.report_id,
            value.as_record(),
        )

    def read_admission_report(
        self,
        report_id: OpaqueId | str,
    ) -> BuildAdmissionReport:
        result = self._read_record(
            "admission_reports",
            report_id,
            BuildAdmissionReport.from_record,
        )
        if result.report_id.value != self._id_value(report_id, "report_id"):
            raise BuildStoreCorruptionError(
                "admission-report filename does not match its content identity"
            )
        return result

    def put_manifest(self, value: BuildManifest) -> OpaqueId:
        if not isinstance(value, BuildManifest):
            raise TypeError("value must be a BuildManifest")
        plan = self.read_plan(value.plan_id)
        admission_report = self.read_admission_report(
            value.admission_report_id
        )
        value.validate_against(plan, admission_report)
        request = self.read_build_request(value.build_request_id)
        attempt = self.read_build_attempt(value.build_attempt_id)
        plan.validate_against(request, attempt)
        expected_predecessor = (
            None
            if request.predecessor_manifest is None
            else request.predecessor_manifest.manifest_id
        )
        if value.predecessor_manifest_id != expected_predecessor:
            raise ValueError("manifest predecessor differs from its approved request")
        for digest in value.module_hashes_by_local_id.values():
            self.read_blob(digest)
        return self._put_record(
            "manifests",
            value.manifest_id,
            value.as_record(),
        )

    def read_manifest(self, manifest_id: OpaqueId | str) -> BuildManifest:
        result = self._read_record(
            "manifests",
            manifest_id,
            BuildManifest.from_record,
        )
        if result.manifest_id.value != self._id_value(
            manifest_id,
            "manifest_id",
        ):
            raise BuildStoreCorruptionError(
                "manifest filename does not match its content identity"
            )
        return result

    def source_package_path(self, manifest_id: OpaqueId | str) -> Path:
        """Return the deterministic location for one immutable source package."""

        return self._packages_root / self._id_value(manifest_id, "manifest_id")

    @staticmethod
    def _package_module_path(module_name: str) -> Path:
        parts = module_name.split(".")
        if any(not part.isidentifier() for part in parts):
            raise ValueError("module_name cannot be represented as a Python path")
        return Path(*parts).with_suffix(".py")

    @staticmethod
    def _package_contents(path: Path) -> dict[str, bytes]:
        if path.is_symlink() or not path.is_dir():
            raise BuildStoreCorruptionError(
                "source package root must be a real directory"
            )
        result: dict[str, bytes] = {}
        pending = [(path, "")]
        while pending:
            directory, prefix = pending.pop()
            try:
                entries = sorted(os.scandir(directory), key=lambda item: item.name)
            except OSError as exc:
                raise BuildStoreCorruptionError(
                    "source package directory cannot be inspected"
                ) from exc
            for entry in entries:
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise BuildStoreCorruptionError(
                        f"source package entry {relative!r} cannot be inspected"
                    ) from exc
                if stat.S_ISLNK(info.st_mode):
                    raise BuildStoreCorruptionError(
                        f"source package entry {relative!r} is a symlink"
                    )
                if stat.S_ISDIR(info.st_mode):
                    pending.append((Path(entry.path), relative))
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise BuildStoreCorruptionError(
                        f"source package entry {relative!r} is not regular"
                    )
                try:
                    descriptor = os.open(
                        entry.path,
                        os.O_RDONLY | os.O_NOFOLLOW,
                    )
                except OSError as exc:
                    raise BuildStoreCorruptionError(
                        f"source package entry {relative!r} cannot be opened"
                    ) from exc
                try:
                    opened = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or opened.st_dev != info.st_dev
                        or opened.st_ino != info.st_ino
                    ):
                        raise BuildStoreCorruptionError(
                            f"source package entry {relative!r} changed during verification"
                        )
                    chunks: list[bytes] = []
                    remaining = opened.st_size
                    while remaining:
                        chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                        if not chunk:
                            raise BuildStoreCorruptionError(
                                f"source package entry {relative!r} ended early"
                            )
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    if os.read(descriptor, 1):
                        raise BuildStoreCorruptionError(
                            f"source package entry {relative!r} grew during verification"
                        )
                    result[relative] = b"".join(chunks)
                finally:
                    os.close(descriptor)
        return dict(sorted(result.items()))

    def _source_package_records(
        self,
        manifest: BuildManifest,
    ) -> dict[str, bytes]:
        build_request = self.read_build_request(manifest.build_request_id)
        build_attempt = self.read_build_attempt(manifest.build_attempt_id)
        plan = self.read_plan(manifest.plan_id)
        report = self.read_admission_report(manifest.admission_report_id)
        manifest.validate_against(plan, report)
        plan.validate_against(build_request, build_attempt)
        records = {
            "APPROVED_BUILD_REQUEST.json": _canonical_bytes(
                build_request.as_record()
            ),
            "BUILD_ATTEMPT.json": _canonical_bytes(build_attempt.as_record()),
            "MATERIALIZATION_PLAN.json": _canonical_bytes(plan.as_record()),
            "STATIC_ADMISSION.json": _canonical_bytes(report.as_record()),
            "BUILD_MANIFEST.json": _canonical_bytes(manifest.as_record()),
        }
        for node in plan.nodes:
            digest = manifest.module_hashes_by_local_id[node.local_id]
            relative = self._package_module_path(node.module_name).as_posix()
            if relative in records:
                raise ValueError("module path collides with build metadata")
            records[relative] = self.read_blob(digest)
        return records

    def verify_source_package(self, manifest: BuildManifest) -> Path:
        """Verify one published package against its content-addressed chain."""

        if not isinstance(manifest, BuildManifest):
            raise TypeError("manifest must be a BuildManifest")
        expected = self._source_package_records(manifest)
        path = self.source_package_path(manifest.manifest_id)
        if not path.is_dir() or self._package_contents(path) != expected:
            raise BuildStoreCorruptionError(
                "source package is absent or differs from its immutable manifest"
            )
        return path

    def publish_source_package(self, manifest: BuildManifest) -> Path:
        """Publish inspectable source plus its complete immutable build chain."""

        if not isinstance(manifest, BuildManifest):
            raise TypeError("manifest must be a BuildManifest")
        records = self._source_package_records(manifest)

        destination = self.source_package_path(manifest.manifest_id)
        with self._lock:
            if destination.is_symlink():
                raise BuildArtifactConflictError(
                    "source package publication path cannot be a symlink"
                )
            if destination.exists():
                if self._package_contents(destination) != records:
                    raise BuildArtifactConflictError(
                        "source package differs from its immutable manifest"
                    )
                return destination
            temporary = Path(
                tempfile.mkdtemp(
                    prefix=".pending-source-package-",
                    dir=self._packages_root,
                )
            )
            try:
                for relative, payload in records.items():
                    target = temporary / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("wb") as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(stream.fileno())
                try:
                    os.rename(temporary, destination)
                except OSError:
                    if not destination.exists():
                        raise
                    if self._package_contents(destination) != records:
                        raise BuildArtifactConflictError(
                            "concurrent source package differs from its manifest"
                        )
                return destination
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)

    def inspection_inputs(
        self,
        *,
        build_request_id: OpaqueId | str,
        build_attempt_id: OpaqueId | str,
        plan_id: OpaqueId | str,
        emitted_module_ids_by_local_id: Mapping[str, OpaqueId | str],
        admission_report_id: OpaqueId | str | None = None,
        manifest_id: OpaqueId | str | None = None,
        receipt_id: OpaqueId | str | None = None,
        verify_source_package: bool = False,
    ) -> MaterializationInspectionInput:
        """Load exact typed projector inputs without importing generated code."""

        from .inspection import MaterializationInspectionInput

        if not isinstance(emitted_module_ids_by_local_id, Mapping):
            raise TypeError("emitted_module_ids_by_local_id must be a mapping")
        build_request = self.read_build_request(build_request_id)
        build_attempt = self.read_build_attempt(build_attempt_id)
        plan = self.read_plan(plan_id)
        emitted_modules = tuple(
            self.read_emitted_module(emitted_module_ids_by_local_id[local_id])
            for local_id in sorted(emitted_module_ids_by_local_id)
        )
        report = (
            None
            if admission_report_id is None
            else self.read_admission_report(admission_report_id)
        )
        manifest = (
            None if manifest_id is None else self.read_manifest(manifest_id)
        )
        receipt = None if receipt_id is None else self.read_receipt(receipt_id)
        source_package_files = None
        if verify_source_package:
            if manifest is None:
                raise ValueError(
                    "source package verification requires a manifest"
                )
            package_path = self.verify_source_package(manifest)
            source_package_files = {
                relative: Sha256Digest.of_bytes(payload)
                for relative, payload in self._package_contents(
                    package_path
                ).items()
            }
        return MaterializationInspectionInput(
            build_request=build_request,
            build_attempt=build_attempt,
            plan=plan,
            emitted_modules=emitted_modules,
            admission_report=report,
            manifest=manifest,
            receipt=receipt,
            source_package_files=source_package_files,
        )

    def inspection_inputs_for_receipt(
        self,
        receipt_id: OpaqueId | str,
        *,
        verify_source_package: bool = True,
    ) -> MaterializationInspectionInput:
        """Load a receipt's complete exact projector inputs."""

        receipt = self.read_receipt(receipt_id)
        return self.inspection_inputs(
            build_request_id=receipt.build_request_id,
            build_attempt_id=receipt.build_attempt_id,
            plan_id=receipt.plan_id,
            emitted_module_ids_by_local_id=(
                receipt.emitted_module_ids_by_local_id
            ),
            admission_report_id=receipt.admission_report_id,
            manifest_id=receipt.manifest_id,
            receipt_id=receipt.receipt_id,
            verify_source_package=(
                verify_source_package and receipt.manifest_id is not None
            ),
        )

    def project_receipt(
        self,
        receipt_id: OpaqueId | str,
        *,
        verify_source_package: bool = True,
    ) -> MaterializedSpecification:
        """Return the strict Materialized Specification for one receipt."""

        from .inspection import project_materialized_specification

        return project_materialized_specification(
            self.inspection_inputs_for_receipt(
                receipt_id,
                verify_source_package=verify_source_package,
            )
        )

    def put_receipt(self, value: BuildReceipt) -> OpaqueId:
        if not isinstance(value, BuildReceipt):
            raise TypeError("value must be a BuildReceipt")
        build_request = self.read_build_request(value.build_request_id)
        build_attempt = self.read_build_attempt(value.build_attempt_id)
        plan = self.read_plan(value.plan_id)
        plan.validate_against(build_request, build_attempt)
        if (
            value.build_request_id != plan.build_request_id
            or value.build_attempt_id != plan.build_attempt_id
        ):
            raise ValueError("receipt and plan name different requests or attempts")
        planned_ids = {node.local_id for node in plan.nodes}
        if not set(value.emitted_module_ids_by_local_id).issubset(planned_ids):
            raise ValueError("receipt indexes an unplanned emitted module")
        emitted = {
            local_id: self.read_emitted_module(identifier)
            for local_id, identifier in value.emitted_module_ids_by_local_id.items()
        }
        if any(module.local_id != local_id for local_id, module in emitted.items()):
            raise ValueError("receipt emitted-module index is stale")
        admission_report = None
        if value.admission_report_id is not None:
            admission_report = self.read_admission_report(
                value.admission_report_id
            )
            if admission_report.plan_id != value.plan_id:
                raise ValueError(
                    "receipt admission report does not belong to its plan"
                )
            expected_hashes = {
                local_id: module.source_hash
                for local_id, module in emitted.items()
            }
            if admission_report.module_source_hashes != expected_hashes:
                raise ValueError(
                    "receipt emitted modules differ from its admission report"
                )
        if value.manifest_id is not None:
            manifest = self.read_manifest(value.manifest_id)
            if (
                manifest.build_request_id != value.build_request_id
                or manifest.build_attempt_id != value.build_attempt_id
                or manifest.plan_id != value.plan_id
                or value.admission_report_id is None
                or manifest.admission_report_id
                != value.admission_report_id
            ):
                raise ValueError("receipt manifest does not belong to its plan")
        if value.materialized and (
            admission_report is None or not admission_report.admitted
        ):
            raise ValueError("an admitted receipt requires an admitted report")
        if value.materialized and set(emitted) != planned_ids:
            raise ValueError("a materialized receipt must index every module")
        return self._put_record(
            "receipts",
            value.receipt_id,
            value.as_record(),
        )

    def publish_materialization_handoff(self, receipt_id: OpaqueId | str) -> dict:
        """Persist exact initial candidate, rejected outputs, checks, and progress."""
        from .handoff import publish_materialization_handoff

        return publish_materialization_handoff(self, receipt_id)

    def read_materialization_handoff(self, receipt_id: OpaqueId | str) -> dict:
        """Read the checks recorded at publication, without evaluating new code."""
        from .handoff import read_materialization_handoff

        return read_materialization_handoff(self, receipt_id)

    def read_receipt(self, receipt_id: OpaqueId | str) -> BuildReceipt:
        result = self._read_record(
            "receipts",
            receipt_id,
            BuildReceipt.from_record,
        )
        if result.receipt_id.value != self._id_value(
            receipt_id,
            "receipt_id",
        ):
            raise BuildStoreCorruptionError(
                "receipt filename does not match its content identity"
            )
        return result

    def receipts_for_build_request(
        self,
        build_request_id: OpaqueId | str,
    ) -> tuple[BuildReceipt, ...]:
        """Return every distinct attempt receipt for one approved request."""

        expected = self._id_value(build_request_id, "build_request_id")
        receipts = tuple(
            receipt
            for path in sorted((self._records_root / "receipts").iterdir())
            if path.is_file() and path.suffix == ".json"
            for receipt in (self.read_receipt(path.stem),)
            if receipt.build_request_id.value == expected
        )
        return tuple(
            sorted(
                receipts,
                key=lambda receipt: (
                    0 if receipt.materialized else 1,
                    receipt.receipt_id.value,
                ),
            )
        )

    def attempts_for_build_request(
        self,
        build_request_id: OpaqueId | str,
    ) -> tuple[BuildAttempt, ...]:
        """Return the attempt, if any, for one single-use build request."""

        expected = self._id_value(build_request_id, "build_request_id")
        attempts = tuple(
            attempt
            for path in sorted((self._records_root / "attempts").iterdir())
            if path.is_file() and path.suffix == ".json"
            for attempt in (self.read_build_attempt(path.stem),)
            if attempt.build_request_id.value == expected
        )
        if len(attempts) > 1:
            raise BuildStoreCorruptionError(
                "a single-use build request has more than one attempt"
            )
        return attempts

    def receipt_for_build_attempt(
        self,
        build_attempt_id: OpaqueId | str,
    ) -> BuildReceipt:
        expected = self._id_value(build_attempt_id, "build_attempt_id")
        matches = tuple(
            receipt
            for path in sorted((self._records_root / "receipts").iterdir())
            if path.is_file() and path.suffix == ".json"
            for receipt in (self.read_receipt(path.stem),)
            if receipt.build_attempt_id.value == expected
        )
        if len(matches) != 1:
            raise BuildStoreCorruptionError(
                "a build attempt must have exactly one terminal receipt"
            )
        return matches[0]


__all__ = [
    "BuildArtifactConflictError",
    "BuildArtifactNotFoundError",
    "BuildStore",
    "BuildStoreCorruptionError",
    "BuildStoreError",
]
