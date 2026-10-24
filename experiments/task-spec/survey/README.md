# survey — generic factor vocabulary

For experiments whose SUT is a survey instrument / framing. Verifier:
`survey_generic`. Surveys have **no correct answer** — the response *is* the
metric — so the verifier is trivially decoupled (`expected` is usually empty).

## Factorable surfaces (generic)

| Factor id | params key(s) | What it varies | Injection |
|---|---|---|---|
| `questionnaire_variant` | `questionnaire_variant` | Which questionnaire file/version | selects `input/questionnaire.<variant>.yaml` |
| `context_variant` | `context_variant` | Framing / scenario context (e.g. membership tier) | `{{ context_variant }}` in `input/context.md` + `MATRIX_PARAM_CONTEXT_VARIANT` |
| `question_order` | `question_order` | Presentation order | env |
| `scale_variant` | `scale_variant` | Response scale (e.g. 1-5 vs 1-10) | env + questionnaire |

## Critical alignment rule

**Question ids must stay identical across levels.** The verifier emits one facet
per `questionId`; if ids drift between variants, arms cannot be aligned. Vary
wording/framing/scale, keep ids stable.

## Verification mode

- **`survey_response`** — validates `survey_result.json` shape and emits a facet
  per answered question (numerical for Likert/scale, categorical for choice,
  textual for free-text), plus the shared `user_feedback` channel if collected.

## Emitted facet contract

Per-question facets keyed by `questionId` (stable across levels) + optional
`user_feedback`. No `expected` needed unless a question has an objectively
correct answer, in which case put it under `expected.constraints`.
