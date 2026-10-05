"""Identify host calculations with the runtime's existing source manifest."""

from pathlib import Path

from agent.episode_contracts import Sha256Digest

from ..identity import _read_exact_file, inspect_runtime_source_manifest


def host_implementation(*adapter_paths):
    root = Path(__file__).resolve().parents[2]
    manifest = inspect_runtime_source_manifest(repository_root=root)
    paths = {Path(__file__), *(Path(path) for path in adapter_paths)}
    return {
        "runtime_manifest": manifest.as_record(),
        "host_adapter_hashes": {
            path.relative_to(root).as_posix(): Sha256Digest.of_bytes(
                _read_exact_file(path, "host experimental implementation")
            ).value
            for path in sorted(paths)
        },
    }


def measurement_implementation():
    from iterative_episode_refiner import records
    from episode_runtime.records import outcomes, runs
    from . import campaign_criteria, campaign_subjects, control_subjects, criteria, instruments, judgments, measurements, observations, refinement_subjects, subjects

    return host_implementation(
        records.__file__, outcomes.__file__, runs.__file__,
        campaign_criteria.__file__, campaign_subjects.__file__, control_subjects.__file__, criteria.__file__, instruments.__file__, judgments.__file__, measurements.__file__, observations.__file__, refinement_subjects.__file__, subjects.__file__
    )
