# MatrAIx Experiments

A **controlled-experiment** layer on top of Playground / Harbor. It is its own
top-level world, **independent from** `application/tasks` and
`application/task-spec`:

| World | Role |
|-------|------|
| `application/tasks` + `application/task-spec` | Single-run task catalog (unchanged by this subsystem) |
| `experiments/` | Factorized experiment tasks, generic verifiers, workbench |

## Core idea

An experiment task declares a **contract**, not a one-off script:

1. **Factor space** — what can vary (`factors` / `levels`), and what stays pinned
   (`constants`)
2. **Axis** — `compareBy: system` (SUT: change the product) or `persona` (PUT:
   change who is simulated)
3. **Design** — how levels expand into arms (`ab_n`, `full_factorial`,
   `fractional`)
4. **Metric contract** — which emitted facets are `primary` / `secondary` /
   `guardrail`, so every arm stays comparable

The Experiments workbench expands that space into Harbor jobs, manages cohorts,
and runs the statistical scorecard. Analysis aligns arms on shared facet keys.

## Author an experiment task

**Start here:**
[docs/application/experiment-task-guide.md](../docs/application/experiment-task-guide.md)

That guide covers decisions (SUT vs PUT, design, assignment), required files,
`experiment.json` / `persona_strategy.json` contracts, injection rules, and a
checklist for onboarding your own task.

Schemas and behavioral rules:
[experiments/task-spec/README.md](task-spec/README.md).

## Layout

```text
experiments/
  README.md                 (this file)
  task-spec/                generic contracts + verifiers (one set per app type)
    schemas/                experiment.json / factor / expected
    web/ os-app/ chatbot/ survey/
    verifiers/              web_generic.py, survey_generic.py, …
  tasks/                    concrete experiment tasks
    web-compare-options/            SUT · web A/B
    survey-onboarding-framing/      SUT · survey framing
    survey-upgrade-copy/            SUT · survey copy
    survey-trust-by-segment/        PUT · persona contrast
```

## Exemplars (what to copy)

| Task | Axis | Type | Use when |
|------|------|------|----------|
| `web-compare-options` | SUT | web | Landing / site variants, conversion |
| `survey-onboarding-framing` | SUT | survey | Same instrument, different framing |
| `survey-upgrade-copy` | SUT | survey | Copy / CTA wording A/B |
| `survey-trust-by-segment` | PUT | survey | Same Qs, different persona segments |

## Run

1. Playground → **Experiments** → pick a task → Configure → launch
2. Results / Analysis / Export (PDF, JSON, CSV)
3. Optional CLI: `matraix experiment list|show|analyze|create`

## Why a separate world

1. **No blast radius** — existing application tasks and verifiers stay untouched
2. **Type-generic** — one generic verifier + factor vocabulary per `appType`;
   authors customize factors instead of forking a product-specific task
3. **Reuse plumbing** — Harbor launch, persona pools, and per-job aggregation
