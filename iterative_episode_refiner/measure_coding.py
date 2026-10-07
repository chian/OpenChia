"""Measure's native coding workspace; checker proposals stay separate from targets."""

import json

from episode_runtime.testing_harness.checker_programs import source_files, validate_program

from .coding_workspace import CodingWorkspace


PROPOSAL = ".openchia-measure.json"
INSTRUCTIONS = """You are the coding call inside EstablishMeasure. Read
.openchia-assignment.json for the parent's original requirements, the current
proposal, independent review and measured feedback. Author the checking
instrument needed to judge those requirements. Target source under target/ is
read-only reference material; derive expected behavior from the specification.

Read returned Question feedback at
episode_request.assignment_context.child_reports[].return.check_review, together
with that report's open_decisions. host_context.inputs.check_design contains the
current proposal; its review_assigned flag identifies a Question review assignment.
Measure receives the returned review through the child report above.

Write your response to .openchia-measure.json using the supplied response schema.
For a program-backed check_design, write Python files under checker/, and put
their relative names in program.files (an array of names relative to checker/).
Set program.entrypoint to module:function. The host captures those exact files,
freezes them with the design, and supplies them to the separate reviewer.
The function takes one context object with source_root (a read-only directory),
materialization (the candidate plan), and input (the case's frozen input). It
returns a JSON value measured by the selected registered predicate at /result.
It may read/import target functions, construct examples, execute them and compare
results. Declare the instrument's third-party dependencies in
checker/.openchia-environment.json and include that file in program.files. Use
the environment recipe schema supplied in target_environment with the selected
Python runtime. The host prepares this instrument recipe through OpenChia PM,
independently of the target's recipe, before executing controls and candidate
checks. A program without a recipe uses the standard library and frozen runtime
libraries. Submit the instrument and its recipe for review and preparation;
recorded preparation diagnostics guide any subsequent recipe repair. Target
environment files in fixtures are data for the checker to examine. Network and
personal credentials are unavailable during checking.

Each positive/negative control supplies fixture={files,materialization,input}
and a requirement-grounded rationale. These are complete synthetic inputs, not
claimed observations and not edits to the target. The host executes the exact
reviewed program on each fixture and checks its expected polarity. Use cases
that discriminate actual correct behavior from plausible defects, including
trivial implementations. Ordinary predicates over existing Run observations
remain available with program=null and observed controls.

Submitting check_design automatically schedules its separate Question review.
Independent review, followed by actual control execution, determines admission.
After review, submit_reviewed_design=true selects that exact reviewed design.
If review or controls fail, revise the program/design and obtain a new review.
Your shell diagnostics help development; the shared harness records validation.
Keep limitations explicit and match the parent's requested judgment purpose.
Changes to the Target Workflow remain the Implementer's responsibility.
"""


class MeasureWorkspace(CodingWorkspace):
    def stage(self, context):
        super().stage(context)
        current = context["host_context"]["inputs"].get("check_design", {}).get("current_design")
        if current and current.get("program"):
            for name, text in current["program"]["files"].items():
                path = self._path("checker/" + name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        self._path(PROPOSAL).write_text("{}", encoding="utf-8")

    def capture(self):
        for name, text in self.source_files.items():
            if self._path(name).read_text(encoding="utf-8") != text:
                raise ValueError("Measure changed its read-only Target Workflow input")
        proposal = json.loads(self._path(PROPOSAL).read_text(encoding="utf-8"))
        if not isinstance(proposal, dict):
            raise ValueError("Measure's proposal must be an object")
        design = proposal.get("check_design")
        if isinstance(design, dict) and design.get("program") is not None:
            program = design["program"]
            if not isinstance(program, dict) or set(program) != {"files", "entrypoint"}:
                raise ValueError("checking program requires files and entrypoint")
            paths = program["files"]
            if (not isinstance(paths, list) or not all(isinstance(path, str) for path in paths)
                    or len(set(paths)) != len(paths)):
                raise ValueError("program.files must list each checker source file once")
            source_files({path: "" for path in paths})
            program["files"] = {
                name: self._path("checker/" + name).read_text(encoding="utf-8") for name in paths
            }
            validate_program(program)
        return proposal
