# OpenChia — architecture review diagrams

Measured from the AST import graph at `main @ 6636fd5a6c` (2026-10-02):
**84 OpenChia-layer files · 24 package nodes · 71 cross-package edges.**

Cycle structure computed with Tarjan SCC and `networkx.simple_cycles`:
**one strongly connected component of three packages, containing two elementary cycles.**

Full findings: [`reports/work-261002.openchia.md`](../../reports/work-261002.openchia.md).
A rendered, self-contained version of these diagrams:
[`reports/openchia-architecture.html`](../../reports/openchia-architecture.html).

Severity is always given by **label**, never by colour alone — red and green sit at
ΔE 4.1 under deuteranopia.

---

## 1. Authority pipeline, with defects mapped

```mermaid
flowchart TD
    H["human ⟷ conversational LLM"]
    D["<b>Duet</b><br/><code>duet_service · duet_store</code>"]
    A["<b>human /approve</b><br/>CAS: BEGIN IMMEDIATE + rowcount guard"]
    B["<b>EpisodeBuilder</b><br/>never receives a DuetStore"]
    R["<b>human /run</b><br/>separate command · re-validated"]
    RUN["<b>isolated Run</b><br/>policy before activation<br/>closure verified 3× · imports closed"]
    REF["<b>IterativeEpisodeRefiner</b><br/>3,850 LOC"]

    HTTP["HTTP leg<br/>~160 adversarial tests"]
    MODEL["MODEL leg<br/>every Run fails"]

    C2["<b>C2 · HIGH</b> — approval race<br/>LLM may replace the draft<br/>while /approve takes 0 args"]
    C34["<b>C3 · C4 · HIGH</b> — unversioned hash<br/>no schema_version<br/>4 JSON Schemas deleted"]
    T15A["<b>T15a · BLOCKER + NO TESTS</b><br/>admission.py AST gate<br/>~29 codes, 0 tests<br/><code>return ()</code> keeps suite green"]
    C5["<b>C5 · HIGH</b> — seccomp default-ALLOW<br/>aarch64 omits 6 syscalls x86_64 denies"]
    C1["<b>C1 · BLOCKER</b> (reproduced)<br/>_freeze_json makes arrays tuples;<br/>broker.py:77 wants a list.<br/>_thaw_json applied to 2 of 3 legs"]

    H --> D --> A --> B --> R --> RUN
    RUN --> HTTP
    RUN --> MODEL
    RUN --> REF
    REF -->|"successor proposal"| A

    D -.-> C2
    A -.-> C34
    B -.-> T15A
    RUN -.-> C5
    MODEL -.-> C1

    classDef sound fill:#eaf7ea,stroke:#0ca30c,stroke-width:2px,color:#0b0b0b
    classDef crit fill:#fbeaea,stroke:#d03b3b,stroke-width:3px,color:#0b0b0b
    classDef high fill:#fdf0e9,stroke:#ec835a,stroke-width:2px,color:#0b0b0b
    classDef untested fill:#f4f4f2,stroke:#898781,stroke-width:2px,stroke-dasharray:5 4,color:#0b0b0b
    classDef plain fill:#ffffff,stroke:#c3c2b7,color:#0b0b0b

    class A,B,R,RUN,HTTP sound
    class C1,T15A,MODEL crit
    class C2,C34,C5 high
    class REF untested
    class H,D plain
```

Four of the five pipeline stages are verified sound. The defects cluster in two
places: **where human intent is captured**, and **where the newest code landed**.

---

## 2. Static dependency graph

```mermaid
flowchart TD
    subgraph ENTRY [" ENTRY "]
        CLI["openchia_cli/<br/>6 OpenChia files of 611 · 1.8%"]
    end

    subgraph COORD [" COORD "]
        HOST["<b>agent/openchia_host.py</b><br/>out=12 · in=0 · 1,748 lines · 52 methods<br/>god object — no seam to test through"]
    end

    subgraph SERVICE [" SERVICE "]
        DS["duet_service<br/>out=6"]
        DST["duet_store<br/>SQLite · CAS sound"]
        OA["openchia_agents"]
    end

    subgraph SUBSYS [" SUBSYS — 1 SCC · 2 elementary cycles "]
        EB["episode_builder<br/>8,696 LOC · 2 test files"]
        IER["iterative_episode_refiner<br/>3,850 LOC · 0 tests"]
        ER["episode_runtime<br/>11,093 LOC"]
    end

    subgraph LIBS [" LIBS "]
        L["episode_library · method_loop · llm_call_library · handoff_library<br/>numeric_control_library · http_call_library · question_table_goal_library<br/><i>7 near-identical packages, no shared registry;<br/>the catalog is a hand-edited 21-entry tuple in planner.py:322</i>"]
    end

    subgraph FOUND [" FOUND "]
        F["agent/duet_contracts (in=8) · agent/episode_contracts (in=7)<br/>agent/episode_contract_models · function_library (in=8)<br/><i>misplaced — the foundation lives inside agent/,<br/>which is what keeps OpenChia and Hermes entangled</i>"]
    end

    subgraph HERMES [" HERMES — ~870k LOC · only 6 edges from 84 files "]
        HM["run_agent · model_tools · tools<br/>openchia_cli.config (bad)<br/>transport (inverted, good)"]
    end

    CLI --> HOST
    HOST --> DS
    HOST --> DST
    HOST --> OA
    HOST --> EB
    HOST --> ER
    HOST --> IER
    DS --> DST
    OA --> HM

    EB -->|3| IER
    IER -->|"1 — inverted edge"| EB
    IER --> ER
    ER -->|7| EB

    EB --> L
    ER --> L
    L --> F
    EB --> F
    ER --> F

    classDef crit fill:#fbeaea,stroke:#d03b3b,stroke-width:3px,color:#0b0b0b
    classDef high fill:#fdf0e9,stroke:#ec835a,stroke-width:2px,color:#0b0b0b
    classDef untested fill:#f4f4f2,stroke:#898781,stroke-width:2px,stroke-dasharray:5 4,color:#0b0b0b
    classDef plain fill:#ffffff,stroke:#c3c2b7,color:#0b0b0b

    class HOST,F high
    class IER untested
    class CLI,DS,DST,OA,EB,ER,L,HM plain
```

**The two cycles, exactly:**

```
episode_builder → iterative_episode_refiner → episode_builder
episode_builder → iterative_episode_refiner → episode_runtime → episode_builder
```

Both run through the single inverted edge `episode_builder → iterative_episode_refiner`
(3 imports). Break that one and both disappear.

---

## 3. Findings

| Severity | ID | Finding | Evidence |
|---|---|---|---|
| **Blocker** | C1 | No Episode that makes a model call can succeed. Frozen tuple fails the broker's `isinstance(…, list)`; Run finalizes FAILED. *Reproduced.* | `protocol.py:395`, `broker.py:77`, `executor.py:1017` |
| **Blocker · no tests** | T15a | The AST gate blocking `eval`/`exec`/`__import__`/`os.system` in LLM-generated code has ~29 rejection codes and zero tests. `return ()` keeps the suite green. | `episode_builder/admission.py` |
| **High** | C2 | `/approve` approves "whatever is current", not what the human read. The store CAS compares current-against-current and cannot catch it. | `openchia_host.py:521`, `duet_service.py:781` |
| **High** | C3 | The content-hash authority chain has no schema version. One added field silently rehashes every design and invalidates all prior approvals. | no `schema_version`; no `PRAGMA user_version` |
| **High** | C4 | The four JSON Schemas were deleted and never replaced. Zero of six needed specs are machine-checkable. | commit `5baa5a3b7d` |
| **High** | C5 | seccomp is default-ALLOW; aarch64 (the macOS container path) omits six syscalls x86_64 denies, plus `io_uring_setup` on both. | `seccomp.py:170`, `:87-114` |
| **High** | C6 | Authority-critical validation implemented twice — function-selection admission and the `content_id` field lists. | `episode_blueprints.py:137`, `planner.py:357` |
| **No tests** | — | Zero tests import `openchia_host.py`, `episode_contract_models.py`, `iterative_episode_refiner/`, `episode_library/`, `numeric_control_library/`, or the editor. `episode_builder/` is touched by exactly two test files. | verified by import grep |
| **Sound** | — | Approval CAS, builder/approver separation, build→run separation, closure verification, closed import finder, policy-before-activation, terminal-ack phasing. | `duet_store.py:960-1054`, `worker.py:348-356` |

---

## 4. What the graph shows that prose didn't

**The shape is good.** High fan-in sits at the base (`duet_contracts` 8,
`function_library` 8, `episode_contracts` 7) and high fan-out at the apex
(`openchia_host` out=12, in=0). That is a correct dependency pyramid — vocabulary at
the bottom, coordination at the top. Only six edges cross to Hermes from 84 files.

**Three defects are visible as geometry, not opinion:**

- `openchia_host` out=12 / in=0 — it depends on everything and nothing depends on it.
  That is *why* no test imports it: there is no seam to test through.
- The foundation layer physically lives in `agent/`. Moving it to `openchia_contracts/`
  is the one cheap cut that makes the package split tractable.
- The cycle is confined to three packages and one inverted edge.
