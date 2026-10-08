# OpenChia — draft design document

**Version:** 0.1  
**Status:** Draft for editing and architectural review  
**Source review date:** 2026-10-07

This draft describes the working checkout reviewed on the date above, including
the ongoing workflow coding and measurement changes. It separates the existing
architecture from recommendations for making it more modular and supportable.
It is based on source and documentation inspection, not a new runtime acceptance
test. No application code was changed to prepare this document.

“Module” below means a cohesive responsibility, which may currently span several
files or share a Python package with other responsibilities.

## Purpose

OpenChia provides a controlled way to turn a human-approved goal into an
implemented, tested Target Workflow.

It combines two substantial systems:

- An inherited Hermes platform: conversations, model providers, tools, profiles,
  plugins, messaging, scheduling, and several user interfaces.
- An OpenChia workflow system: human authorization, structured workflow design,
  materialization, iterative refinement, isolated execution, and recorded
  validation evidence.

The central architectural problem is maintaining a clear boundary between
**what the human authorized**, **what the system implemented**, and **what
execution actually demonstrated**.

## 1. System concepts and lifecycle

| Concept | Meaning |
|---|---|
| **Duet** | The human, the restricted conversational model, and the host protocol through which they design and approve work. |
| **Target Workflow** | The complete task workflow being designed, implemented, refined, tested, or executed. |
| **Episode** | A node within a workflow, with declared behavior, interfaces, and permitted child relationships. |
| **Candidate revision** | One exact implementation state of the Target Workflow. |
| **Build** | Materialization of an approved design, followed by the authorized refinement and validation lifecycle. |
| **Refinement campaign** | The recorded process of assigning work, changing candidates, constructing measurements, and assessing results. |
| **Run** | One execution under a specific frozen contract and execution configuration. |
| **Evidence** | Recorded observations tied to exact candidates, requirements, instruments, and Runs. |

The current lifecycle is:

```text
Human + Duet
    |
    v
Design Target Workflow
    |
    v
Approve exact workflow and applicable authority
    |
    v
Start build
    |
    +--> Builder materializes implementation
    |        |
    |        v
    |    Candidate, partial results, and diagnostics
    |        |
    |        v
    +--> Refiner assigns and performs authorized work
             |
             +--> Design / implementation changes
             +--> Measurement construction
             +--> Isolated validation Runs
             +--> Evidence and progress assessment
             |
             v
       Verified build OR an explicit unresolved/stopped outcome

Verified implementation --> Subsequent authorized Target Workflow Runs
```

One build start owns the build–refine–validate cycle. Routine work within the grant
should continue automatically. Changes beyond that authority return through the
Duet.

Three judgments must remain distinct:

- **Approval:** the work is authorized.
- **Admission:** the implementation satisfies structural and execution-boundary
  requirements.
- **Verification:** evidence supports satisfaction of the original behavioral
  requirements.

Successful admission, a clean process exit, or a favorable model report cannot
substitute for verification.

This lifecycle is established by
[ADR 0007](../adr/0007-build-owns-iterative-finalization.md) and implemented through
the [build job](../../agent/openchia_build_job.py).

## 2. Current module organization

### Workflow and authority modules

These contain OpenChia’s principal product behavior.

| Module and current location | Responsibility and main outputs | Dependencies and external capabilities |
|---|---|---|
| **Duet authority** — `agent/duet_contracts.py`, `duet_service.py`, `duet_store.py` | Maintain design state, human approvals, frozen workflows, authority history, and validated transitions. | Workflow contracts, SQLite, profile-owned filesystem. Model proposals arrive through the surrounding conversation system. |
| **Application lifecycle** — `agent/openchia_host.py`, `openchia_build_*`, `openchia_run_*` | Connect user commands to authority, builds, refinement, execution, cancellation, continuation, and result publication. | Nearly all OpenChia services; profile configuration, threads/async tasks, durable stores. |
| **Workflow contracts and blueprints** — `agent/episode_contracts.py`, `episode_blueprints.py`, related modules | Define and translate the structured Target Workflow, Episode contracts, identities, and architecture representations. | Primarily Python data validation and serialization; currently housed within the broad `agent` package. |
| **Builder** — `episode_builder/` | Plan implementation, emit source, attach declarations, perform static admission, and produce manifests, receipts, and repairable partial results. | Workflow contracts, reusable libraries, model transport, artifact storage, environment declarations. Generated Target Workflow code is not executed in the host during admission. |
| **Revision authority and workspace** — `iterative_episode_refiner/service.py`, `contracts.py`, `workspace.py` | Represent exact baselines, human notes, proposed revisions, change classifications, and architecture/materialization views. | Duet authority, Builder records, stored evidence. This responsibility shares a package with autonomous refinement. |
| **Autonomous refinement** — the campaign, runtime, coordination, control, measurement, and finalization modules in `iterative_episode_refiner/` | Decompose work, admit operations, manage candidates and measurements, coordinate conflicts, assess progress, and publish verified outcomes. | Builder, shared experiment service, model and coding adapters, campaign storage, numerical control. |
| **Experiment and validation service** — `episode_runtime/testing_harness/` | Describe, dispatch, inspect, and continue experiments; connect criteria, subjects, Runs, and observations. | Builder admission, Run execution, artifact stores, measurement definitions. Despite its name, this is production infrastructure. |
| **Run execution** — `episode_runtime/` | Register and execute exact admitted builds, enforce host/worker communication, broker permitted requests, and retain execution evidence. | OS isolation, systemd or a container runtime, filesystem storage, model/HTTP brokers when the workflow uses them. |
| **Target environment preparation** — `episode_runtime/target_environment*`, `environment_executor.py` | Resolve a candidate’s dependency recipe, retain a lock and environment identity, and prepare dependencies for isolated execution. | PM, package sources or caches, existing execution backends. Installation authority is separate from Run authority. |
| **Human workflow coding** — `agent/workflow_coding.py`, `workflow_editing.py`, `episode_builder/edited_sources.py` | Maintain a human-directed coding conversation and working copy; submit an exact reviewed snapshot through ordinary authority and build paths. | Native coding adapter, filesystem workspace, persistent conversation/events, exclusive editing ownership. **Currently under development.** |
| **Terminal inspection** — `openchia_cli/inspector/`, `refiner_command.py` | Project recorded campaigns and Runs into interactive trees, details, history, plain text, and JSON. | Read access to SQLite/artifact files; `prompt_toolkit` for interactive display. No model service or execution authority is required. |

The current composition point is
[OpenChiaHost](../../agent/openchia_host.py). Builder behavior is concentrated
around [EpisodeBuilder](../../episode_builder/service.py), while experiment
dispatch lives in
[ExperimentService](../../episode_runtime/testing_harness/service.py).

### Reusable workflow foundations

These express behavior that can be selected and composed into workflows.

| Module | Responsibility | Dependencies and external capabilities |
|---|---|---|
| `method_loop/` | Generic Episode loop, nesting, identities, communication, and component bindings. | Python standard library; collaborators supply domain behavior. |
| `function_library/` | Typed, selectable function definitions and bindings, including refinement and testing functions. | `method_loop` and domain-specific implementations. External capabilities depend on the selected functions. |
| `episode_library/` | Source-backed reusable Episode designs and their registrations. | Function definitions, bindings, handoff contracts, numerical components. |
| `handoff_library/` | Typed parent requests and child results, including correlation and payload admission. | Generic Episode and function contracts. |
| `numeric_control_library/` | Progress credit, rarefaction, and continuation decisions. | Numerical data and generic function/loop contracts; no model service is needed for the calculation itself. |
| `llm_call_library/` | Typed model-call mechanics for explicitly composed Episodes. | A supplied model transport; provider connectivity and credentials belong to the host adapter. |
| `http_call_library/` | Typed HTTP-call mechanics for Episodes. | A host-supplied HTTP broker enforcing the permitted requests. |
| `question_table_goal_library/` | Contracts for one workflow-wide question-table goal with scoped, read-only Episode views. | Shared goal state and function bindings; Episodes submit proposals rather than directly owning separate table stores. |

These libraries are important existing modular boundaries. Refactoring should
preserve their selectability and avoid merging domain policy into the generic
loop.

### Platform and user-facing modules

These support both OpenChia and inherited Hermes capabilities.

| Module | Responsibility | Dependencies and external capabilities |
|---|---|---|
| `run_agent.py`, conversation/provider portions of `agent/` | Model/tool conversation loop, prompt construction, compression, retries, session lifecycle, and provider adaptation. | Configured model endpoint, authentication, optional provider SDKs, tool registry, session storage. |
| `providers/`, provider plugins | Discover provider profiles and provider-specific configuration. | Selected provider services and credentials; profile-scoped plugin configuration. |
| `tools/`, `model_tools.py`, `toolsets.py` | Declare tools, resolve availability, dispatch calls, and enforce toolset selection. | Capability-specific binaries, services, credentials, or execution backends. |
| `tools/environments/` | Execute ordinary agent terminal commands through local and remote backends. | Selected shell, SSH/container/cloud backend, and associated credentials. |
| `plugins/`, plugin loader, skills, MCP support | Extend providers, tools, memory, context handling, platforms, and workflows. | Plugin-specific packages/services; MCP may use subprocess or network transports. |
| `hermes_state.py` and siblings | Store conversational sessions, messages, model settings, and searchable history. | SQLite and profile-owned storage. |
| `openchia_cli/`, `cli.py` | CLI startup, commands, setup, configuration, and terminal interaction. | Terminal, `prompt_toolkit`, configuration and application services. |
| `tui_gateway/`, `apps/shared/` | JSON-RPC session backend and shared client types/transport utilities. | Python backend; stdio or WebSocket transport; TypeScript tooling for clients. |
| `ui-tui/` | Inherited React/Ink terminal client. | Node runtime, terminal, JSON-RPC backend. |
| `apps/desktop/` | Electron desktop application and React interface. | Desktop runtime, packaged backend, optional native integrations. |
| `web/`, CLI web server and routers | Browser dashboard and web API. | React build tooling, FastAPI/Uvicorn, browser and network/authentication configuration. |
| `gateway/`, platform plugins | Messaging adapters, session routing, delivery, and gateway lifecycle. | Enabled messaging services, SDKs, credentials, and durable state. |
| `cron/` | Scheduled job ownership, dispatch, and delivery integration. | Scheduler host, persistent job state, optional messaging destinations. |
| `acp_adapter/` | Editor integration through the Agent Client Protocol. | ACP client and stdio transport. |
| `pm/`, `hermes_platform/` | Managed dependencies and runtimes; passive machine facts and executable/resource discovery. | Filesystem, package sources/caches, platform tooling. Discovery itself should not install or launch anything. |

The presence of these interfaces does not establish OpenChia feature parity
across them. The current
[`openchia` entry point](../../openchia_cli/openchia_main.py) selects the classic
Python CLI and explicitly excludes the separate TypeScript TUI.

## 3. Internal organization of the Refiner

The Refiner has two distinct layers:

1. **Reasoning roles** propose work, designs, edits, measurements, and
   interpretations.
2. **Host policy and storage** determine which operations are admissible and what
   the evidence establishes.

The role graph currently contains:

| Role | Responsibility |
|---|---|
| **Parts** | Own the assigned whole, divide work, coordinate dependencies, and assess contributions against the whole’s requirements. |
| **Designer** | Carry a scoped solution through design, implementation, and independent acceptance. |
| **Implementer** | Change the assigned candidate under an established implementation measure. |
| **Support** | Supply relevant, source-linked guidance for a specific knowledge gap. |
| **Question** | Resolve an uncertainty that affects the caller’s next decision. |
| **Measure** | Produce a reusable measuring function and demonstrate the adequacy of its checks. |
| **Verify** | Independently evaluate the exact candidate and return evidence, counterexamples, and limitations. |

The roles are defined in
[refinement contracts](../../function_library/refinement_contract.py) and composed
through [reusable Episode designs](../../episode_library/refinement.py).

A maintainable decomposition of the host side should make the following
responsibilities explicit:

- **Campaign state:** assignments, invocations, current candidate, operation
  history.
- **Admission and coordination:** permitted actions, scope ownership, conflicts,
  parent decisions.
- **Candidate materialization:** source changes, plan changes, static admission,
  environment recipe changes.
- **Measurement:** requirements, checks, instruments, controls, baseline
  comparisons.
- **Evaluation:** dispatch through the shared experiment service.
- **Progress control:** evidence-derived achievement and numerical continuation.
- **Finalization:** bind accepted evidence to the exact build result.
- **Queries:** read-only projections for context, reports, CLI inspection, and
  history.

The current measurement work is moving toward private components assembled into
a completed composite measure. That contract should be stabilized before
reorganizing these files: partial construction must not silently replace the
parent’s established measure.

## 4. Execution boundaries and external requirements

There are three execution systems with different responsibilities:

| Boundary | Purpose | Authority |
|---|---|---|
| **Ordinary agent tools** | Perform conversational tool actions, including terminal commands. | Session tool availability and tool-specific permissions. |
| **Coding sessions** | Edit candidate files and run coding diagnostics. | A scoped working directory, permitted edits, and the selected coding backend. |
| **Episode Runs** | Execute admitted workflows and produce correlated runtime evidence. | Frozen workflow, admitted source, declared environment, runtime policy, and host-brokered capabilities. |

A coding diagnostic can help an Implementer decide what to change. It does not
automatically become acceptance evidence.

The main external requirements are:

| Capability | Required when |
|---|---|
| Managed Python environment | Running the Python host and services. Exact dependencies belong in the existing manifests and locks. |
| SQLite and durable filesystem | Maintaining authority, conversations, artifacts, campaign state, and Run records. |
| Model provider endpoint | Running Duet conversations, model-based building, refinement reasoning, or model-using workflows. |
| Native Codex or Claude coding backend | Using the corresponding implementation or human coding path. Availability must match the pinned provider route. |
| systemd or Docker/Podman backend | Executing isolated Runs or preparing Target Workflow environments through that backend. |
| Package index or artifact cache | Preparing dependencies that are not already available in an accepted environment. |
| Approved HTTP destinations and credentials | Executing workflows with declared HTTP capabilities. |
| Node/frontend build tooling | Building or running applicable TypeScript clients and their tooling. |
| Messaging/cloud/browser/audio services | Only when the corresponding optional platform or tool is enabled. |

The existing [CodingSession interface](../../agent/refinement_coding.py) is a
useful reusable boundary for both autonomous implementation and human-directed
coding.

Model routing is another boundary that must remain explicit:

- The Refiner uses the owning Duet’s model/provider configuration.
- Target Workflow test Runs use the Target Workflow’s approved launch
  configuration.
- Host adapters retain credentials and expose only scoped operations to workers.

## 5. State ownership, persistence, and history

| State | Owner and storage | Required meaning |
|---|---|---|
| Conversation history | `SessionDB`, profile-owned SQLite | What the user and conversational agent exchanged. |
| Workflow authority | `DuetStore`, `<profile>/openchia/authority.sqlite3` | What was proposed, validated, and human-approved. |
| Refinement campaign | `CampaignStore`, within the existing Duet database | Immutable admitted operations and commits; indexes accelerate current-state reads. |
| Build artifacts | `BuildStore`, `<profile>/openchia/episode_builder/` | Exact requests, plans, source, manifests, receipts, and diagnostics. |
| Run records | `RunStore`, `<profile>/openchia/episode_runs/` | Registrations, execution events, audit records, and terminal evidence. |
| Human coding work | `<profile>/openchia/workflow_edits/` plus authority records | Editable working copies, conversation progress, and exact submitted snapshots. |

These stores do not form one transaction across SQLite and the filesystem.
Correlated identities, hashes, idempotent publication, and recovery logic
therefore form part of the architecture.

For supportability, each persisted artifact type should document:

- Its authoritative writer.
- Its identity and schema version.
- Whether it is immutable, an index, or a disposable cache.
- Which other artifacts it references.
- How incomplete publication is detected and recovered.
- Which reader versions can interpret it.

History should always identify its observation boundary. A campaign commit and a
Run event are different positions. Their relationship must come from recorded
references; timestamps alone cannot manufacture a shared historical state.

The existing [terminal inspector](refiner_terminal_viewer.md) already follows this
approach. Its generic `Snapshot`, `Node`, `Detail`, and `Link` values provide a
foundation for additional domain views.

## 6. Recommended module boundaries

**Recommendation: retain one repository and the existing host/worker
architecture, while making package dependencies and service interfaces
narrower.** Separate deployment services are not needed to achieve the initial
modularity goals.

The proposed logical arrangement is:

```text
CLI / terminal inspector / RPC clients / messaging / automation
                            |
                            v
                  Application services
          Duet lifecycle | Build lifecycle | Coding | Run control
                            |
                            v
                     Domain services
          Authority | Builder | Refiner | Validation
                            |
                            v
                  Shared workflow foundations
          Contracts | Episode loop | Selectable libraries

Application composition also supplies:
    Storage adapters
    Model and HTTP brokers
    Coding adapters
    Environment preparation
    Run executors
    Profile configuration

Read-only queries:
    Stored records --> Domain projections --> Terminal / JSON / other clients
```

These are responsibility boundaries, not a proposed bulk directory rename.

**Shared contracts should be small and deliberate.** Move genuinely shared
identities and frozen workflow data out of the broad `agent` package where that
removes unwanted dependencies. Keep campaign-specific and executor-specific
contracts with their owners. Avoid turning a new `common` package into another
collection of unrelated code.

**Application services should own sequencing.** They coordinate approval checks,
build starts, cancellation, continuation, and publication. They should not
implement measurement policy or know how individual terminal widgets render.

**Builder should own materialization.** Its public operations should accept
explicit approved inputs and return exact receipts, partial artifacts, and
diagnostics. Refiner and human editing should use that same admission path.

**Refiner should own refinement policy.** Its core operations should depend on
supplied capabilities for materialization, evaluation, coding, and persistence.
Concrete CLI setup and backend selection should remain outside that policy.

**Validation should remain shared.** The existing experiment service should serve
Target Workflow tests, checker/control experiments, and Refiner execution.
Role-specific execution loops would create competing meanings of success and
recovery.

**Inspection should remain independent.** Extend the current reader/projection
design for future Target Workflow or environment views. Interactive terminal and
machine-readable output should consume the same projections. Keep `/refiner`
separate from `/episode`.

The principal service boundaries should have contracts equivalent to:

| Boundary | Input | Output |
|---|---|---|
| Materialize | Approved workflow, source/plan inputs, explicit model route | Receipt, artifact references, partial results, admission diagnostics |
| Evaluate | Exact candidate, criteria, inputs, execution authority | Experiment and Run references, observations, explicit gaps |
| Code | Workspace, permitted scope, coding route, conversation input | Proposed edits, diagnostics, resumable coding state |
| Apply campaign operation | Actor, operation, evidence, expected campaign state | Admitted commit or structured rejection |
| Inspect | Domain identity and live/history position | Snapshot or detail with stable links and reported gaps |

These contracts should refine existing interfaces wherever possible.

## 7. Concrete supportability issues

| Finding | Consequence | Proposed response |
|---|---|---|
| Builder, Refiner, and runtime import one another, including for shared contracts. | A change in one area requires knowledge of several packages and complicates isolated testing. | Separate shared data definitions from orchestration; place cross-service coordination behind the existing application layer. |
| `agent/` contains both general conversational infrastructure and OpenChia authority/lifecycle code. | Package names do not clearly identify ownership or allowed dependencies. | Establish explicit subdomains and dependency rules before moving files. |
| “Refiner” covers revision authority/workspace services as well as an executing nested campaign. | Readers can confuse approval-related services with autonomous work execution. | Document and separate these responsibilities while retaining their shared identities and evidence links. |
| Several inherited modules remain very large. | Changes have broad review and regression scope. | Extract by responsibility when touching them; prioritize provider handling, lifecycle, and persistence boundaries. |
| Production validation lives under `testing_harness`. | It is easy to mistake runtime infrastructure for developer test utilities. | Clarify its public role now; consider a focused rename during a later extraction. |
| Cross-store publication and recovery are distributed across lifecycle code. | Failures are harder to diagnose and continuation behavior is harder to audit. | Document publication protocols and make ownership of each recovery path explicit. |
| Some architecture documentation describes earlier behavior. | Maintainers may implement against conflicting descriptions. | Label documents as current, proposed, or superseded and connect accepted decisions to implementation status. |
| Profile, secret, model-route, and execution scopes cross many callbacks and thread boundaries. | Configuration can silently come from the wrong owner. | Pass or bind explicit owning scope at service boundaries; preserve the existing profile isolation rules. |

Two concrete documentation differences need resolution:

- The older architecture overview and CLI help describe build and execution
  separation in terms that do not explain build-owned validation.
- [ADR 0005](../adr/0005-target-workflow-execution-backends.md) selects containers
  as the intended default, while
  [current executor selection](../../episode_runtime/executor_selection.py)
  chooses systemd automatically on suitable Linux hosts.

A separate proposal,
[interpreting Episode wiring instead of emitting it](../adr/0004-interpret-the-episode-wiring-instead-of-emitting-it.md),
remains proposed. It should be evaluated independently from package cleanup
because it changes the materialization model.

## 8. Support and verification requirements

A supportable build should let an operator move from a visible failure to:

```text
Duet / approval
    -> build request and receipt
    -> campaign and assignment
    -> candidate revision
    -> experiment and Run
    -> observation, diagnostic, or unmet requirement
```

The CLI and inspector should expose those relationships without needing to run a
model or reconstruct meaning from free-form logs.

User-visible outcomes should distinguish at least:

- Awaiting an owner decision.
- Missing or inadequate measurement.
- Candidate admission failure.
- Environment preparation failure.
- Runtime failure.
- Interrupted or cancelled work.
- Exhausted continuation with unresolved requirements.
- Verified completion.

For each boundary, verification should test behavior across the real integration
path:

| Boundary | Essential invariant |
|---|---|
| Authority → build | Work cannot silently use stale approval or expand the grant. |
| Builder → worker | Only exact admitted source and environment enter execution. |
| Coding → candidate | Workspace edits do not become authoritative merely because files changed. |
| Refiner → measurement | Changed or stale evidence cannot silently earn fresh progress. |
| Experiment → Run | Repeated submission does not create duplicate execution or duplicate credit. |
| Interruption → continuation | Completed work and evidence survive; unfinished work remains explicit. |
| Profile A → B → A | Configuration, credentials, state, and callbacks remain with the owning profile. |
| Records → history view | Historical inspection does not substitute present-day state for missing past records. |

Prompt caching and message-role invariants also remain platform requirements:
modularization must not rebuild long-lived prompt prefixes, change toolsets
mid-conversation, or inject invalid message sequences.

## 9. Suggested refinement sequence

1. **Agree on responsibility names and authority boundaries.** Resolve the
   overloaded Refiner terminology and document the current lifecycle.
2. **Stabilize the work in progress.** Finish the human coding handoff and
   measurement-composition contracts before reorganizing their implementation.
3. **Protect one complete vertical path.** Approval → build → repair → validation
   → verified result, including interruption and continuation.
4. **Extract shared contracts selectively.** Start with concrete imports that
   force Builder, Refiner, or runtime to depend on unrelated host code.
5. **Separate lifecycle orchestration from domain policy.** Preserve behavior and
   persisted formats during this step.
6. **Consolidate query ownership.** Reuse domain projections across context
   generation, reports, CLI output, and history where their semantics actually
   match.
7. **Reduce the largest implementation concentrations.** Split by cohesive
   responsibility in focused changes.
8. **Evaluate larger architectural changes separately.** Generated versus
   interpreted wiring and execution-backend defaults deserve their own decisions
   and validation.

Historical artifacts, their hashes, and active Run contracts must retain their
original meaning throughout this process.

## 10. Decisions for the next design revision

The most useful decisions to make next are:

- Which interfaces are required OpenChia product surfaces, and which remain
  inherited platform capabilities?
- Which records and APIs are stable external contracts versus internal
  implementation details?
- Should revision authority/workspace services become a separate module from
  autonomous refinement?
- What is the final parent-adoption contract for composite measurements?
- Which execution backend should be the supported default?
- What are the supported compatibility and recovery guarantees for older builds,
  Runs, and campaign histories?

Those decisions would let the next version turn this module map into a concrete
dependency plan, with explicit owners, public interfaces, and migration steps
for each boundary.
