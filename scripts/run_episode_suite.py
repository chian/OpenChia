#!/usr/bin/env python3
"""Run the OpenChia Episode test suite: one pytest process per file, in parallel.

The suite is listed in ``tests/episode_suite.txt`` (directories or files).
Tests listed in ``tests/episode_suite_known_failures.txt`` are deselected so
the gate is green and blocks *new* failures; ``--check-known`` runs only those
and reports which now pass, so the list shrinks as they are fixed.

Exit status: 0 when every selected test passed or was skipped, 1 otherwise.
Standard library only.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "tests" / "episode_suite.txt"
KNOWN = ROOT / "tests" / "episode_suite_known_failures.txt"
# pytest exit codes: 0 passed, 5 nothing collected (everything deselected/skipped).
OK_CODES = {0, 5}


def entries(path: Path) -> list[str]:
    """Non-comment lines; anything after `#` on a line is a note."""
    lines = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def suite_files() -> list[str]:
    files: set[str] = set()
    for entry in entries(SUITE):
        target = ROOT / entry
        if target.is_dir():
            files.update(str(p.relative_to(ROOT)) for p in target.rglob("test_*.py"))
        elif target.is_file():
            files.add(entry)
        else:
            raise SystemExit(f"episode suite entry does not exist: {entry}")
    return sorted(files)


def known_failures() -> tuple[set[str], dict[str, list[str]]]:
    """Whole files (collection errors) and per-file node IDs."""
    whole, nodes = set(), {}
    for entry in entries(KNOWN) if KNOWN.exists() else []:
        if "::" in entry:
            nodes.setdefault(entry.split("::", 1)[0], []).append(entry)
        else:
            whole.add(entry)
    return whole, nodes


def run_file(python: str, path: str, extra: list[str], timeout: int) -> tuple[str, int, list[str], str, float]:
    started = time.monotonic()
    command = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE", path, *extra]
    try:
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        output, code = done.stdout + done.stderr, done.returncode
    except subprocess.TimeoutExpired as exc:
        output, code = f"{exc.stdout or ''}{exc.stderr or ''}\nTIMEOUT after {timeout}s", 124
    failed = sorted({re.sub(r" - .*", "", line).split(" ", 1)[1]
                     for line in output.splitlines() if line.startswith(("FAILED ", "ERROR "))})
    summary = (output.strip().splitlines() or [""])[-1]
    return path, code, failed, output, time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python", default=os.environ.get("HERMES_PYTHON") or sys.executable)
    parser.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 2)))
    parser.add_argument("--timeout", type=int, default=600, help="seconds per test file")
    parser.add_argument("--check-known", action="store_true",
                        help="run only the known failures and report which now pass")
    parser.add_argument("--verbose", action="store_true", help="print full output of failing files")
    args = parser.parse_args()

    whole, nodes = known_failures()
    if args.check_known:
        jobs = [(path, []) for path in sorted(whole)] + [(path, ids) for path, ids in sorted(nodes.items())]
        jobs = [(path, ids) for path, ids in jobs]
    else:
        jobs = []
        for path in suite_files():
            if path in whole:
                continue
            jobs.append((path, [arg for node in nodes.get(path, []) for arg in ("--deselect", node)]))

    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(run_file, args.python, path, extra, args.timeout) for path, extra in jobs]
        results = [future.result() for future in futures]

    if args.check_known:
        fixed = [path for path, code, failed, _, _ in results if code in OK_CODES]
        still = sum(len(failed) or (code not in OK_CODES) for _, code, failed, _, _ in results)
        for path in fixed:
            print(f"now passing, remove from known failures: {path}")
        print(f"known-failure entries checked: {len(results)} files; still failing tests: {still}")
        return 0

    bad = [(path, code, failed, output) for path, code, failed, output, _ in results if code not in OK_CODES]
    for path, code, failed, output in bad:
        print(f"\n✗ {path} (exit {code})")
        for node in failed:
            print(f"    {node}")
        if args.verbose or not failed:
            print("\n".join("      " + line for line in output.strip().splitlines()[-40:]))
    slowest = sorted(results, key=lambda item: item[4], reverse=True)[:5]
    print(f"\nEpisode suite: {len(results)} files, {len(bad)} failing; "
          f"{len(whole)} files and {sum(map(len, nodes.values()))} tests deselected as known failures.")
    print("slowest: " + ", ".join(f"{path} {seconds:.0f}s" for path, _, _, _, seconds in slowest))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
