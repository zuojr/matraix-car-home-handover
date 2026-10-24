# Experiments task-spec

Generic, **type-internal** contracts for factorized experiment tasks. This is a
sibling of `application/task-spec`, not a replacement — it reuses that spec's
**shared-core metric contract** (`application/task-spec/docs/shared-core-metrics.md`)
so experiment arms and normal runs speak the same facet vocabulary.

> **Onboarding checklist (start here):**
> [docs/application/experiment-task-guide.md](../../docs/application/experiment-task-guide.md)
> — SUT vs PUT, required files, `experiment.json` / `persona_strategy.json`,
> injection, metric keys, and common failure modes.

## What lives here

- `schemas/` — JSON Schemas:
  - `experiment.schema.json` — the factor space + signals + metricContract a task
    declares.
  - `factor.schema.json` — a single factor (dimension + levels).
  - `expected.schema.json` — OPTIONAL per-level correctness ground truth.
- `web/`, `os-app/`, `chatbot/`, `survey/` — the **generic factor vocabulary**
  for each app type: which surfaces are factorable, and how their `params` inject
  into the trial.
- `verifiers/` — one **generic verifier per app type** (`web_generic.py`, ...),
  plus `_shared.py` with the shared-core facet/context/envelope helpers. These
  are *not* per-task; a task selects one via `experiment.json.verifier`, or sets
  `verifier: "custom"` and ships its own in `tests/`.

## Behavioral by default

The default posture is **behavioral**: we measure *what the persona did and how
they felt*, not whether they were "correct". A task declares three things in
`experiment.json`:

- **`factors` → `levels` → `params`** — the stimulus that varies. Injected into a
  trial two ways:
  1. templated into `instruction.md` / `input/context.md` as `{{ param_name }}`,
  2. exported as environment variables `MATRIX_PARAM_<UPPER_NAME>`.
- **`signals`** — declarative Tier-2 extraction: each entry lifts a field out of
  the `outputArtifact` into a shared-core facet (`key`, `kind`, `role`,
  `context`). This is how behavioral metrics (chosen option, decision basis,
  effort, ...) get emitted without custom verifier code. Survey tasks often leave
  `signals: []` and rely on stable `questionId`s instead (see the guide).
- **`metricContract`** — which emitted facet keys are `primary` (OEC, drives the
  decision), `secondary` (diagnostic), and `guardrail` (must-not-regress).

`user_feedback.json` (from `input/self_report_schema.yaml`) is always folded in
automatically, so keys like `overall_experience_rating` / `effort_rating` are
available to the metricContract for free.

## Optional correctness path

Only when a level has an objectively-correct answer: add
`variants/<levelId>/expected.json` (shape in `expected.schema.json`, located via
`HARBOR_VARIANT_DIR`) and set `submissionSchema`. The verifier then flips
`task_outcome` to failed on violations. Most experiments skip this entirely.

## Alignment rule

Every level of a factor MUST emit the **same facet keys** so the analysis layer
can align arms without special-casing. Because signal `key`s (or survey
`questionId`s) are declared once at the task level, this holds by construction.

See each per-type README for the concrete factor vocabulary.
