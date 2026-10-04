# Live non-runnable candidate repair — 2026-10-04

The corrected host accepted a live Implementer edit without requiring the
rejected candidate to execute first. This establishes the three requested
observations below, not a successful build, Target Workflow Run, or scheduling
answer. The subsequent automatic validation failed; terminal status is `failed`.

## Observed path

| Required observation | Recorded evidence |
| --- | --- |
| Implementer receives the existing rejection for the exact candidate and authorized harness. | Run event 3 is a real `change` model request containing candidate `refinement_5d83718755e331417b4e63e4f08076b864c018fc88f0ab6a066984a4a2625e76` and source rejection `refinement_5aad20fb730bc4f2fadd064db38fec14696ced23f724c5735b5ab66b1d0a6e01`. Its receipt reports `module_exports_incomplete`, `missing_module`, and `request_payload_binding_mismatch`. The source request's candidate, harness and capability references match the assignment's authorized local evaluation binding. |
| Source repair is reachable before executing the rejected candidate. | The same model input has `baseline_required: false`. Reconstruction is event 2; the next action is the model edit request at 3, not a Target Workflow evaluation. |
| A live model edit reaches ordinary host edit admission. | Event 4 contains the 30,450-character model response. Event 5 submits it as a `change` proposal. Event 6 returns `proceed: true` and a durably changed candidate. No edit was supplied by the operator. |

The accepted change replaces
`built_episode_schedule_reasoner_882e4692ccf4.py` and updates the permitted
`/episodes/schedule_reasoner/parts/node_plan` materialization detail. The proposed
source is 8,356 UTF-8 bytes. Normal host checks admitted the change under the
existing assignment and design plan; this is **edit admission**, not admission
of the resulting executable package.

- Change set: `refinement_ba75eeb9e8f84317a9daa7647414ce0fa8524e73c0de56c1d32355fc83612004`.
- Before candidate: `refinement_5d83718755e331417b4e63e4f08076b864c018fc88f0ab6a066984a4a2625e76`.
- After candidate: `refinement_5408908c27229fb73ff05b24945c2cc27e38e04d20ebdbf9df5b14811fe6c272`.
- Before source hash: `sha256:00c96abc98911134efa0ae996e66c1ae52cfd742c06df864cef0b255005ae447`.
- After source hash: `sha256:a84e3432004d28833b0d2b906fa5f5953e7d6c41b898e179fb673f3c3a96a2f8`.

Previous candidate observations become stale after this change. No new passing
validation, positive progress measurement or final acceptance is claimed. The
new candidate still has `source_admission_ref: null`.

## Execution and provenance

- Entry: the shared `ExperimentService.continue_interrupted`, using the existing
  systemd executor and the owning Duet's restored model binding.
- Experiment: `experiment_b198903b85e9d173331a04cf668e140ed6cd0f5e2d08673a6b15d1bba2afd3b7`.
- Predecessor: `run_d2c7d6667c1d34664cef783f6127803114823e928ad60115621d24776e52306b`.
- New physical Run: `run_532ffdb89af09743a7bd6c34e57f14d6d6ba4121e3f3bff36b43410b1b1fcf66`.
- Model: `gpt-5.6-sol-900k`, `xhigh`, frozen Codex Responses route. Target Workflow
  launch settings were not substituted for the Duet binding.
- Host source: `3f55bd665a`, a detached verification checkout based on the
  host-only baseline correction `1aab50878e`. Only two worker dependencies were
  restored to their previously recorded bytes; no candidate repair was made
  in that checkout. This is not a product-code rollback.
- Worker manifest: `runtime_source_manifest_78a8a8a0b7fb18e68953aa32ba949246b98d4d35fa3daf2f50e2b47b59dcd553`.
  Full equality was checked before continuation. Event 2 records 84 matching
  worker frames, zero remaining frames and no divergence.

The existing store is
`/home/chia/repos/OpenChia-acceptance-0RN3r9BH/home/openchia/`.
Run events are under `episode_runs/events/<run_id>/`, numbered from zero;
terminal evidence is under `episode_runs/evidence/<run_id>.json`.
Candidate, assignment, evaluation and change-set records remain in the shared
`authority.sqlite3`; source blobs remain in the existing Builder store.

Exact receipt anchors:

- Model request event: `run_event_11a0b6b021aa4dbd90350f63e24847a5f1afd0ca4cd54fb08928a19bb8d9c6a2`,
  hash `sha256:e65f32a1d8a6fc15a67c0fbec74b952b98047ce76cb7e5fd097905cab67ea996`.
- Model response hash: `sha256:51301b6411f82dad4e8fb0f37399762231627b7355250cb7f6397eb5a1c48c54`.
- Host edit decision event: `run_event_ce574df4e3869326b7947054413ba99fbf3931cbcbe64f858b69a9051c1de88c`,
  hash `sha256:2e97b2335c2c2e922ac527e238ac2cef26bd739370ad587e9be918e955b4b11c`.
- Terminal evidence: `run_evidence_f729021a0bcf00515d69a68462aa57ebe17e6231ceebda2798f1e6f7b6525fef`,
  hash `sha256:dcb1811f1a2816e2a63fc6db44967a8681ec08bf3c6dcf1f58a367b462950082`.

The terminal audit was read through `RunStore.read_audit_log` and
`read_evidence`. No systemd Episode worker remained afterward.

## Limits and the failure after admission

This saved candidate already had a rejection from a **local** check. It
therefore verifies the live repair path under the corrected host, but does not
isolate the correction's acceptance-to-local evidence-sharing case or prove
that this path failed on the previous host. The newer parent-report format is
also not exercised by this older pinned Run.

Event 7 automatically requests local evaluation of the changed candidate.
During source admission, the older Builder scans existing build attempts and
encounters a newer stored repeatable-call record containing `synthesize_report`.
Its parser rejects that field, producing `BuildStoreCorruptionError` and event
8, `run_failed`. The nested cause is schema-version incompatibility, not proof
that the stored bytes are corrupt or that the candidate is behaviorally wrong.
The edit is durable; package validation and Target Workflow execution did not
complete. That later compatibility problem was not repaired in this narrow
verification task.

An initial continuation of the newer communication experiment produced seven
completed Designer responses but did not reach Implementer: measurement
coverage and prerequisite-reference checks rejected its proposals. That Run,
`run_41b002e70545db9fe50c156f7f58c5f5476875c96d0676ff55e90f3443efe116`,
was normally cancelled before switching to the saved Implementer state above.
It is not counted as evidence of repair. No acceptance requirements, credit
rules, active worker source, or model-authored candidate output were rewritten
to make either execution pass.
