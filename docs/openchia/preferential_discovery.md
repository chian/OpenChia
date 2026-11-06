# Joint preferential-discovery yield estimation

`numeric_control_library/preferential_discovery.py` is an unchanged copy of
[`question_pipeline/utilities/rarefaction.py` from nano-graphrag at
`60a167f`](https://github.com/chian/nano-graphrag/blob/60a167f9eeda0c9ea2ca294724174948947baf3f/question_pipeline/utilities/rarefaction.py).
Its SHA256 is
`02af19652d69f368ee8875d3b27cad0bb2bbc8d1f8274344b72a4437092cdd35`.
The MIT notice is retained in `THIRD_PARTY_NOTICES.md`.

The model is `joint_preferential_discovery_v1`, implemented by the original
`_IncidenceEstimator`. It jointly fits acquisition-observation status and new
discovery counts through a shared latent variable, with an exponentially
declining rank trend. It retains full ordered attempt history and performs a
warm-start MAP fit using the original standard-library BFGS implementation.
Forecasts include approximate Laplace uncertainty for next discoveries and
remaining discoveries.

This is the original nano-graphrag adaptation of a joint sampling/outcome model.
It does not implement Diggle et al.'s spatial Gaussian-process/Cox-process model
or explicitly model selection among alternative search targets. Its uncertainty
is conditional on its model and approximate numerical fit, not a distribution-free
guarantee that the scientific search is exhausted.

## Library selection

The thin OpenChia connection is `numeric_control_library/preferential_control.py`.
Both definitions are included in EpisodeBuilder's reusable function catalog,
have content-derived definition IDs and pinned source references, and load through
the standard `LibraryFunction` mechanism:

| Export | Component ID | Interface |
| --- | --- | --- |
| `JOINT_PREFERENTIAL_DISCOVERY` | `rarefaction.joint_preferential_discovery_v1` | `rarefaction.preferential_incidence` |
| `COMPOSE_PREFERENTIAL_CONTROLLER` | `controller_composition.compose_preferential_controller` | `controller.compose_preferential_incidence` |

The first opens the original estimator. Call `observe(label, identities,
observation_status=...)` for each completed unit and `snapshot()` to obtain its
report. This preserves ordered attempts, identity deduplication, fit parameters
and the warm-start inverse Hessian. Repeated identities can inform the history
without earning another discovery.
The public observation-status constants are `PREFERENTIAL_OBSERVED`,
`PREFERENTIAL_FAILED` and `PREFERENTIAL_EXCLUDED`.

The second connects the complete original numerical component to the existing
`Grain.controller` factory protocol. It retains nano-graphrag's channel projection,
relaxed geometric hypervolume credit, uncertainty propagation, continuation
verdicts and optional threshold adapter. Each Episode path receives independent
per-channel estimator histories. A new epoch opens fresh histories.

```python
from numeric_control_library import (
    COMPOSE_PREFERENTIAL_CONTROLLER,
    PreferentialChannelSchema,
    PreferentialControllerConfig,
    PreferentialIncidenceObservation,
)
from method_loop import Grain

factory = COMPOSE_PREFERENTIAL_CONTROLLER.load()(
    epoch="literature-assessment-v1",
    channel_schema=PreferentialChannelSchema.single(),
    control=PreferentialControllerConfig.uniform(
        ("overall",), gamma=0.01, rho=0.0, streak_length=1,
    ),
)
grain = Grain("page", "one completed reader", "accepted evidence identities", factory)

# A Leaf result or parent-owned child-result projection supplies this record:
observation = PreferentialIncidenceObservation(("stable-evidence-identity",))
```

`PreferentialIncidenceObservation` is the original observation record with
OpenChia's `ClosedRecord` base. Its inherited `failed(reason, ...)` and
`excluded(reason, ...)` constructors preserve distinct upstream meanings:

- **Observed:** an evaluated acquisition, including a genuine zero-discovery result.
- **Failed:** acquisition did not produce a usable observation; the failure enters
  the joint observation model. Independently accepted partial evidence is retained.
- **Excluded:** no statistical attempt; exclusion does not advance fitted attempt
  rank. Any explicitly supplied accepted identities remain retained as upstream.

Parent Episodes project the returned evidence identities into their own
observations. They do not add a child's numerical credit or copy its estimator
history. One child return is one observation at the parent's grain.

The fitting parameters retain upstream names and defaults: `window_size=8`,
`subsample_size=4`, `alpha=0.05`, with `1 <= subsample_size < window_size`.
The sizes specify minimum attempted/evaluated data before fitting; they do not
truncate history or limit Episode execution. Missing or unidentified forecasts
are explicit unavailable bands and cannot establish numerical saturation.

## Compatibility

The existing `rarefaction.paired_incidence` definition estimates Chao2 richness
and singleton-rate next yield from unordered anonymous counts. Those counts
cannot reconstruct the ordered discoveries and attempt status needed here.
The new implementation therefore has its own explicit interface and composition;
it does not silently substitute different mathematics under an old definition ID.

Use the new composition in an explicitly declared Episode binding that supplies
its original typed observations. Existing frozen Architecture contracts that
select `rarefaction.numeric_incidence`, and the source-backed reference Episodes
that declare that interface, retain their existing binding. Catalog availability
does not automatically migrate approved workflows.

## Validation

The test fixture `tests/numeric_control_library/fixtures/preferential_upstream.json`
was produced by executing the pinned upstream module independently. The transfer
tests compare every numerical/controller transition for single-channel and
partitioned-channel histories, including failures, exclusions and repetitions.
Additional behavior tests check order sensitivity, observation/failure separation,
independent scopes and epochs, the real Episode loop, function-catalog resolution
and generated-code constructor admission.

```bash
scripts/run_tests.sh tests/numeric_control_library/ tests/episode_builder/test_preferential_catalog.py
```
