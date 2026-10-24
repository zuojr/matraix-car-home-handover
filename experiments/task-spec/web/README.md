# web — generic factor vocabulary

For experiments whose SUT is a website / web product. Verifier: `web_generic`.

## Factorable surfaces (generic, not task-specific)

| Factor id | params key(s) | What it varies | Injection |
|---|---|---|---|
| `target_url` | `target_url` | The site / staging build under test | `{{ target_url }}` in instruction + `MATRIX_PARAM_TARGET_URL` |
| `content_build` | `content_build` | Which content/build variant of the same site | env + template |
| `start_state` | `start_url`, `start_query` | Entry point / prefilled state | env + template |
| `instruction_variant` | `instruction_variant` | Task-framing wording (held constant unless it IS the factor) | template select |

Authors may add task-scoped factors with a `task_` prefix; keep the declared
signal `key`s identical across levels.

## Behavioral extraction (default)

`web_generic` is behavioral by default: presence of `outputArtifact` is the
`task_outcome` check, then it reflects the task's declared `signals` into facets.
A typical "compare N options, choose one" task produces a
`plan_comparison.json` with fields like `decision_subject_label`, `basis_primary`,
`exploration_style`, `reason`, `task_options_considered[]`, and declares signals
mapping them to `chosen_option`, `decision_basis`, `exploration_style`,
`options_considered_count`, `decision_reason`. See
`experiments/tasks/web-compare-options` for the worked example.

## Optional correctness modes

Only when a level ships `expected.json`, `web_generic` additionally checks it via
`submissionSchema`:

- **`compare_choose`** — `expected.option_ids` (id -> label),
  `require_all_options_considered`, `source_url`, and `constraints` are validated;
  a wrong/invalid pick flips `task_outcome` to failed.
- **`fill_submit` / `search_select`** — `expected.constraints` are checked
  verbatim.

## Emitted facet contract (shared-core)

Always emits the shared-core `task_outcome` context (`outcome_status`,
`goal_completion_ratio`, `goal_completion_bucket`, `verifier_mode`,
`primary_failure_reason`, `outcome_explanation`, `completion_evidence`), the
declared `signals` contexts (e.g. `decision`, `decision_process`), and a
`user_feedback` context when `input/self_report_schema.yaml` produces
`user_feedback.json`. See `application/task-spec/docs/shared-core-metrics.md` for
the canonical keys.
