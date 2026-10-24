# Product concept survey (FocusLoop)

MatrAIx **survey** reference task: read product context and a structured
questionnaire, then submit persona-aligned answers as JSON.

Task contents:

- `instruction.md`, `task.toml`, `tests/`
- `input/context.md`, `input/questionnaire.yaml`
- `persona_strategy.json`, `reporting.json` (task root; part of the task).
  The strategy is a **40 / 35 / 25** mix on `economic_motivation`. Other
  filter dims use `{value: null}` (eligible, not in the mix). Playground
  Task-plan / Dataset Pull and
  `generate_dev_personas.py --strategy application/tasks/example-survey_product-feedback`
  all honor that mix. `--task … --per-cell` is grounding cells, not this file.

This task reuses `application/shared-survey-form`. Playground mounts `input/` into
the trial; sampling and reporting stay at the task root.

See [Application Tasks](../README.md).

## Smoke run

Oracle (no persona model):

```bash
uv run matraix run -p application/tasks/example-survey_product-feedback -a oracle
```

Persona agent:

```bash
uv run python application/scripts/generate_application_job.py \
  --task application/tasks/example-survey_product-feedback \
  --execution-mode auto \
  --persona-ids 0042

export ANTHROPIC_API_KEY="sk-ant-..."
export MATRIX_SURVEY_TASK_PATH=application/tasks/example-survey_product-feedback
uv run matraix run -c configs/jobs/application-task-job-recipe/example-survey-product-feedback-auto-n1.yaml
```

See [Application Quickstart](../../../docs/quickstart.md) for the UI path and full env vars.

## What this exercises

- Task-local survey docs in `input/` plus the shared `shared-survey-form` runtime
- `/app/input` → read materials → `/app/output/survey_result.json` contract
- Schema verifier (question coverage + interest scale)
- **Proportional cohort by declared shares** — `persona_strategy.json` authors the
  `economic_motivation` mix (40 % Cost-sensitive / 35 % Value-driven / 25 %
  Premium-seeking) as weights on the filter values, so the Playground **Task plan**
  tile synthesizes/draws to that mix (N editable). See
  [Declared target shares](../../task-spec/docs/authoring-bundle.md#persona_strategyjson).
