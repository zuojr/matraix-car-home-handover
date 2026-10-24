# web-compare-options (landing-page signup A/B)

A self-contained **web design / copy A/B conversion** experiment. Two variants of
a product landing page are hosted as compose sidecars; the persona lands on one
and decides, as themselves, whether to sign up. The measured outcome is
**signup conversion**.

This task is **behavioral** — there is no per-level ground truth. The metric is
*whether the persona converted and why*, not whether a choice was "correct".

> **Authoring checklist / full contract:**
> [docs/application/experiment-task-guide.md](../../../docs/application/experiment-task-guide.md)

## Contract (`experiment.json`)

- **`compareBy`** `system` (SUT), **`design`** `ab_n`, **`armAssignment`**
  `shared` (the same cohort sees both designs in isolated sessions → paired,
  higher-powered; the sim is memoryless so there is no carryover).
- **Factor** `target_url` (`space: system`, `source: stimulus`) has two levels:
  `variant_a` (value/savings framing, compact — `baseline`) and `variant_b`
  (premium/outcome framing, highlighted "Most popular" plan). **Same product and
  prices in both**; only copy framing + layout change, so conversion deltas
  isolate the design effect.
- `instruction.md` references the factor as `{{ target_url }}`. This uses the
  generic stimulus mechanism (see `experiments/task-spec/README.md`): for **every**
  stimulus param of the arm's cell, the experiment layer both templates
  `{{ param_name }}` in `instruction.md` / `input/context.md` **and** exports
  `MATRIX_PARAM_<UPPER_NAME>`. Nothing here is `target_url`-specific — a task may
  declare any number of factors (or a level with a multi-key `params` block), plus
  pinned `constants`, and each arm substitutes its own combination. This task just
  happens to have one factor, so its only param is `MATRIX_PARAM_TARGET_URL`.
- **`outputArtifact`**: `signup_decision.json` — its presence is the task_outcome
  check; `action_taken` is reflected as the primary `signup_clicked` signal.
- **`metricContract`**: `signup_clicked` (primary / OEC — conversion rate),
  `decision_basis` + `overall_experience_rating` (secondary), `effort_rating` +
  `trust_level` (guardrail).

## Environment (`task.toml`)

- `[environment].definition = application/shared-web-playwright` (Playwright main)
- `[environment].local_compose = application/web-landing-ab_pricing` (the two
  `web-a` / `web-b` nginx sidecars; see that package's README)
- Each nginx logs to `/var/log/site/web-<x>.access.log`, collected from its
  service. A `GET /signup` there is **objective, server-side proof of
  conversion**, independent of the persona's self-report.

## Scoring today vs. objective upgrade

The shared `web_generic` verifier reflects the persona's `signup_decision.json`
into signals, so the current primary signal is the **self-reported**
`action_taken`. The access logs are collected as **objective corroboration**; a
task-specific verifier can later score `signup_clicked` directly from the
collected `web-<x>.access.log` (`GET /signup`) to make the OEC fully behavioral.

## Run the verifier locally

```bash
MATRIX_OUTPUT_DIR=/tmp/out \
HARBOR_VERIFIER_DIR=/tmp/verifier \
bash tests/test.sh
```
