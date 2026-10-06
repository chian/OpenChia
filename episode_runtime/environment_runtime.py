"""Read-only verification of a prepared Target Workflow dependency tree."""

from pathlib import Path

from agent.duet_contracts import canonical_json
from agent.episode_contracts import Sha256Digest

from .identity import RuntimeIdentityError, _read_exact_file, _walk_regular_files
from .target_environment import PreparedTargetEnvironment


_dependency_importer = None
_dependency_imports_enabled = False


def bind_dependency_importer(importer):
    """Called only by the verified bootstrap before worker initialization."""
    global _dependency_importer
    if _dependency_importer is not None:
        raise RuntimeIdentityError("dependency importer is already bound")
    _dependency_importer = importer


def enable_dependency_imports():
    """The worker calls this only after installing the registered confinement."""
    global _dependency_imports_enabled
    if _dependency_importer is None:
        raise RuntimeIdentityError("prepared environment has no verified dependency importer")
    _dependency_importer.enable_dependencies()
    _dependency_imports_enabled = True


def require_dependency_imports_enabled():
    if not _dependency_imports_enabled:
        raise RuntimeIdentityError("Target Workflow dependency code requires the confined worker")


def verify_target_environment(package_path, prepared):
    """Authenticate bytes without importing a dependency or executing setup."""
    if not isinstance(prepared, PreparedTargetEnvironment):
        raise TypeError("prepared environment must have an admitted identity")
    package = Path(package_path)
    if package.is_symlink() or not package.is_dir() or package.name != prepared.environment_id.value:
        raise RuntimeIdentityError("Target Workflow environment directory differs from its identity")
    metadata = _read_exact_file(package / "TARGET_ENVIRONMENT.json", "prepared environment record")
    if metadata != canonical_json(prepared.as_record()).encode("utf-8"):
        raise RuntimeIdentityError("Target Workflow environment record differs from its identity")
    site = package / "site-packages"
    files = dict(_walk_regular_files(site, python_only=False))
    if set(files) != set(prepared.file_hashes):
        raise RuntimeIdentityError("Target Workflow environment has missing or unmanifested files")
    for relative, expected in prepared.file_hashes.items():
        if Sha256Digest.of_bytes(_read_exact_file(files[relative], f"dependency {relative!r}")) != expected:
            raise RuntimeIdentityError(f"dependency {relative!r} differs from prepared environment")
    return site
