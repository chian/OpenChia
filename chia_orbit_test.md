# Goal: demonstrate OpenChia end to end through a stochastic orbital-stability study

Starting from a fresh Duet conversation, have OpenChia design, build, refine, validate, and run a Target Workflow that solves the problem below. OpenChia must own the build → refine → validate cycle after the initial approval and start.

Completion requires independently checked simulation results—not merely successful construction, an exhausted Episode, or a Run that exits without errors.

## 1\. Scientific question

**How does the probability of an orbit remaining within a specified radial region change with the strength of a periodically varying attractive field and random external forcing?**

Determine that probability for every parameter combination below. The answers are unknown in advance. Do not require or assume any particular number of stable or unstable cases.

“Stable” here means **remaining within the specified region for the specified simulation duration**, not mathematical stability for all future time.

## 2\. Equations and initial conditions

Simulate a unit-mass particle in two spatial dimensions. All quantities are dimensionless.

Let

r=(x,y),  r=√(x²+y²).

Its acceleration is

\\\[
\\ddot{\\mathbf r}
\=
\-\\frac{\[1+a\\sin(0.7t)\]\\mathbf r}{r^3}
\+0.02
\\begin{pmatrix}
\\cos(0.4t)\&\\sin(0.4t)\\\\
\\sin(0.4t)\&-\\cos(0.4t)
\\end{pmatrix}
\\mathbf r
\+\\sigma\\boldsymbol{\\eta}(t).
\\\]

These terms represent:

- A central attractive field whose strength varies periodically.
- A rotating, noncentral field.
- A random force with correlated values over time.

Every trajectory starts from

r(0)=(1,0),  ṙ(0)=(0,1).

Use all **12 combinations** of

a∈{0, 0.15, 0.30},   σ∈{0.002, 0.01, 0.03, 0.08}.

The simulation horizon is

T=40π.

## 3\. Exact definition of the random forcing

Generate the forcing on a fixed time grid, independently of the numerical integrator:

tⱼ=0.1j,  ρ=e^{-0.1/0.5}.

For each trajectory, draw independent two-component standard-normal vectors Zⱼ, then set

\\\[
\\boldsymbol{\\eta}\_0=\\mathbf Z\_0,
\\\]

\\\[
\\boldsymbol{\\eta}\_{j+1}
\=
\\rho\\boldsymbol{\\eta}\_j
\+\\sqrt{1-\\rho^2}\\mathbf Z\_{j+1}.
\\\]

Define \\(\\boldsymbol{\\eta}(t)\\) by linear interpolation between those grid values. Generate enough points to bracket T.

Use trial seeds 20261005+k, with k=1,2,…. Freeze and record the random-number generator, Gaussian sampler, and software versions before execution. Save the generated forcing arrays.

Use the same forcing realization for a given trial number across all parameter combinations. **Numerical refinements must reuse those exact arrays; changing the integration step must never generate a different random force.**

## 4\. Outcomes to measure

Stop an individual trajectory at its first occurrence of:

| Condition | Recorded outcome |
|---|---|
| r≤0.5 | `inner_exit` |
| r≥2 | `outer_exit` |
| Reaching T without either crossing | `survived` |

Detect crossings during integration, not merely at saved output times.

For each parameter combination, estimate

p(a,σ) = P(0.5\<r(t)\<2 for every t∈\[0,T\]).

An inner or outer exit is a valid scientific result, **not a failed test or failed workflow**. A solver error is neither an exit nor a survival.

## 5\. Required iterative simulation

The Target Workflow must resolve two separate uncertainties.

### Numerical accuracy

Begin with maximum integration step h=0.05. Re-run each forcing realization at progressively finer resolution.

For adaptive solvers, begin with relative tolerance 10⁻⁷ and absolute tolerance 10⁻⁹. At each refinement, halve the maximum step and divide both tolerances by ten. Account explicitly for the forcing interpolation knots.

Require agreement across **two consecutive refinement comparisons**:

- Identical trajectory outcome.
- First-exit times differ by at most 10⁻³, where applicable.
- Every position and velocity component differs by at most 10⁻⁴ at common comparison times before the earlier termination.

Comparison times are t=0,0.1,0.2,…, plus the shared terminal time where applicable.

Retain unresolved trajectories and continue investigating their numerical accuracy. Do not discard them or substitute easier seeds.

### Sampling uncertainty

Accumulate independent forcing realizations at checkpoints

n∈{512, 1024, 2048}.

At each checkpoint calculate

\\\[
\\widehat p=\\frac{\\text{number of surviving trajectories}}{n},
\\qquad
b\_n=\\sqrt{\\frac{\\ln(1440)}{2n}},
\\\]

and report

\[L,U\]= \[max(0,p̂-bₙ), min(1,p̂+bₙ)\].

Stop sampling a parameter combination when

U-L≤0.10.

This uses a conservative [Hoeffding bound](<https://www.stat.cmu.edu/~cshalizi/sml/21/lectures/06/lecture-06.html>), with the error allowance divided across all 12 combinations and three checkpoints. It accounts for checking results repeatedly before stopping. Sampling uncertainty and numerical accuracy must be reported separately.

The sample checkpoints and physical horizon define this scientific experiment. They are **not** substitutes for the Episodes’ yield-governed continuation rules.

## 6\. Independent verification and outputs

Through the existing unified testing harness, independently integrate the first 16 forcing realizations for each parameter combination using:

- A different numerical integration method.
- A separately implemented evaluation of the stated equations.
- The same stored forcing arrays and initial conditions.

Those comparisons must satisfy the numerical agreement requirements above. Agreement provides numerical validation, not an analytical proof.

Produce:

- A 12-row table containing parameters, sample counts, outcome counts, estimated survival probabilities, uncertainty intervals, and numerical-validation results.
- A plot of survival probability across the parameter grid.
- Per-trajectory outcomes and exit times, plus the forcing and numerical records needed for replay.
- A short interpretation distinguishing supported findings from unresolved distinctions between configurations.

Do not impose energy or angular-momentum conservation checks: the specified forcing does not generally conserve them.

## 7\. Hard completion criteria

The goal is complete only when:

1. The actual Duet → architecture → build → IterativeEpisodeRefiner → validation → Target Workflow execution sequence has run.
2. All 12 parameter combinations satisfy both numerical and sampling requirements, with no unresolved numerical failures hidden in the counts.
3. Independent verification passes.
4. A fresh Target Workflow Run reproduces the accepted results from the saved inputs and declared environment, within the specified tolerances.
5. The saved records identify the approved specification, candidate revisions, model configurations, environment, Runs, and final results.

There is no requirement to manufacture a repair if the first build works. If repairs are needed, OpenChia must perform and validate them itself.

## 8\. Rules that cannot be broken

- Do not manually write or repair the generated Target Workflow, alter its reports, or supply its scientific answers.
- Fix demonstrated OpenChia system defects generically; do not introduce orbit-specific shortcuts into the builder or refiner.
- Do not weaken the equations, parameter grid, tolerances, or acceptance criteria to obtain a pass.
- Do not replace real execution with mocked model responses or fabricated evidence.
- Do not bypass host admission, credit assignment, rarefaction, or continuation controls.
- Do not stop legitimate iteration merely because its current strategy looks unproductive.
- Provider failures must stop the affected execution visibly and preserve its state; they must not be counted as scientific outcomes. Resume through supported continuation.
- Do not change global machine security settings or personal coding-agent configuration.
- Use the existing checkout, runtime, environment preparation, and unified testing/replay machinery.

**The deliverable is an empirically established, reproducible orbital-survival map—and evidence that OpenChia produced it through its complete workflow without manual repair of the Target Workflow.**
