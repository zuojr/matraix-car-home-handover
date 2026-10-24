# survey-onboarding-framing (SUT · survey)

**Hypothesis:** framing the onboarding survey around outcomes (what the user
will achieve) rather than features raises reported satisfaction and
continuation intent, without increasing perceived effort.

## Contract

| Field | Value |
|-------|-------|
| `compareBy` | `system` (SUT) |
| `design` | `ab_n` |
| `armAssignment` | `shared` (same cohort, both framings) |
| Factor | `context_variant` — `feature` (baseline) vs `outcome` |
| Primary | `onboarding_satisfaction` |
| Secondary | `likelihood_to_continue`, `preferred_next_step` |
| Guardrail | `perceived_effort` |

Stimulus: `MATRIX_PARAM_CONTEXT_VARIANT` / `{{ context_variant }}` selects
framing text in `input/context.md`. **Question ids stay identical** across
levels so arms remain comparable. `signals: []` — metrics come from survey
`questionId`s via `survey_generic`.

## Authoring

Copy this folder for other survey framing / copy A/Bs. Full checklist:
[docs/application/experiment-task-guide.md](../../../docs/application/experiment-task-guide.md).
