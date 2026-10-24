# Authoring bundle

Onboarding and diagrams: [`../README.md`](../README.md).

Per-type file layouts for tasks under `application/tasks/<task-name>/`.
Part of [task-spec README](../README.md) **Step 2**. Per-type **diagrams** are in each
type README ([survey](../survey/README.md), [chatbot](../chatbot/README.md),
[web](../web/README.md), [os-app](../os-app/README.md)).

Each runnable task lives under `application/tasks/<task-name>/` and always
includes `instruction.md`, `task.toml`, `tests/`, `reporting.json`, and
`persona_strategy.json` (target cohort / Playground sampling defaults).
Supplementary files differ by application type:

### Survey

```text
instruction.md                 # short scenario / requirements
reporting.json                 # batch aggregation policy (contextRules)
persona_strategy.json          # target cohort + Playground sampling defaults
input/
  context.md                   # product concept (optional)
  questionnaire.yaml           # questions + askRationale / askConfidence
```

Do **not** add `input/output_schema.md`. The platform derives the answer
envelope from `questionnaire.yaml` and writes `survey_result.json`.

### Chatbot

```text
instruction.md                 # conversation goal
reporting.json                 # batch aggregation policy (contextRules)
persona_strategy.json          # target cohort + Playground sampling defaults
input/
  context.md                   # application background (optional)
  protocol.md                  # chat API / MCP contract (optional)
  chatbot.yaml                 # runtime connection metadata
  self_report_schema.yaml      # user_feedback.json
```

Platform-managed harness artifacts (`transcript.json`,
`application_result.json`) are documented in
[`eval_artifacts.md`](eval_artifacts.md), not in per-task files.

### Web / OS-app

```text
instruction.md                 # task goal, steps, optional submission JSON schema
reporting.json                 # batch aggregation policy (contextRules)
persona_strategy.json          # target cohort + Playground sampling defaults
input/
  context.md                   # scenario / product background (optional)
  self_report_schema.yaml      # user_feedback.json (optional)
```

Prefer verifying from browser/OS traces and final state. When state is hard to
read, an agent submission schema may still live inline in `instruction.md`.
Persona self-report uses the same `input/self_report_schema.yaml` convention as
chatbot tasks.

### Quick reference

| Concern | survey | chatbot | web / os-app |
|---|---|---|---|
| Scenario | `instruction.md` | `instruction.md` | `instruction.md` |
| Background context | `input/context.md` | `input/context.md` | `input/context.md` (optional) |
| Structured input | `input/questionnaire.yaml` | `input/chatbot.yaml`, optional `protocol.md` | — |
| Objective evidence | platform `survey_result.json` | platform harness artifacts | trace/state (optional agent submission) |
| Persona self-report | — | `input/self_report_schema.yaml` | `input/self_report_schema.yaml` |
| Batch reporting policy | `reporting.json` | `reporting.json` | `reporting.json` |
| Target cohort / sampling | `persona_strategy.json` | `persona_strategy.json` | `persona_strategy.json` |

### `persona_strategy.json`

Lives at the **task root** next to `reporting.json`. Most tasks declare a
**target cohort** with `dimensionFilters` (and/or `cohortId`). Field values may
use defaults; the file itself and a cohort declaration are checked in CI.

Playground uses this for Single / Random / All / Stratified defaults.

```json
{
  "schemaVersion": "1.0",
  "pool": "persona/datasets/matraix-persona-dev-sample",
  "sources": ["Nemotron"],
  "dimensionFilters": {
    "age_bracket": ["25-34", "35-44"],
    "region": ["North America"]
  },
  "sampling": {
    "mode": "stratified",
    "fields": ["age_bracket", "region"],
    "allocation": "perCell",
    "perCell": 2
  },
  "seed": 42
}
```

| Field | Notes |
|---|---|
| `schemaVersion` | Use `"1.0"` |
| `dimensionFilters` / `cohortId` | Non-empty filters and/or a saved `cohortId` — who this task is for |
| `sources` | Optional source allow-list |
| `pool` | Defaults to matraix-persona-dev-sample; use `matraix-persona-1m` for production coverage |
| `sampling` | **How** to draw from the filtered pool (required). Tagged by `sampling.mode` |

**`sampling.mode`**

| Mode | Block fields | Cohort size |
|---|---|---|
| `single` | optional `personaId` | 1 (operator may override in UI) |
| `random` | `sampleSize` | exactly `sampleSize` |
| `all` | (none) | entire filtered pool (subject to product max) |
| `stratified` | `fields` + `allocation` + quota fields below | depends on allocation |

**Stratified `sampling.allocation`**

| Allocation | Set | Omit | Cohort size |
|---|---|---|---|
| `perCell` | `perCell` | `sampleSize` | `N × #cells` |
| `proportional` | `sampleSize` | `perCell` | exactly `sampleSize` (quotas ∝ cell population) |
| `equalTotal` | `sampleSize` | `perCell` | exactly `sampleSize` (`ceil(N/#cells)` then clip) |

Rules:

1. Every `sampling.fields` entry must also appear under `dimensionFilters` with allowed values.
2. Thin / missing cells → generate a local pool with `generate_dev_personas.py --strategy <task>` (same generate path as Playground, including `--overlay` custom dimensions), sample from `matraix-persona-1m`, widen filters / sources, or reuse a **Save as dataset…** YAML pool. Sampling never synthesizes personas at draw time.
3. Do not set both `perCell` and `sampleSize` under stratified sampling.

**Declared target shares (proportional mix)**

`proportional` alone draws quotas ∝ the *pool's* cell population. To instead
synthesize/draw to a mix **you** declare (e.g. 40 % Cost-sensitive / 35 %
Value-driven / 25 % Premium-seeking), put the shares in the contract. Two
equivalent forms:

```jsonc
// Form A — explicit sampling.portions
"dimensionFilters": { "economic_motivation": ["Cost-sensitive", "Value-driven", "Premium-seeking"] },
"sampling": {
  "mode": "stratified", "fields": ["economic_motivation"],
  "allocation": "proportional", "sampleSize": 20,
  "portions": { "economic_motivation": { "Cost-sensitive": 0.4, "Value-driven": 0.35, "Premium-seeking": 0.25 } }
}
```

```jsonc
// Form B — weights authored on the filter values (portions derived automatically)
"dimensionFilters": { "economic_motivation": { "Cost-sensitive": 0.4, "Value-driven": 0.35, "Premium-seeking": 0.25 } },
"sampling": { "mode": "stratified", "fields": ["economic_motivation"], "allocation": "proportional", "sampleSize": 20 }
```

Notes:

- Weights are relative (normalized), so `40/35/25` and `0.4/0.35/0.25` are equivalent.
- The shared-cohort **size** is `sampleSize` (Playground's Task-plan tile lets the
  operator override N; the declared shares still define the mix). Synthesis honors
  the mix as *exact* marginal allocation (`50/30/20` at N=20 → `10/6/4`).
- Shares currently apply to a **single** stratify dimension; the dim must be a real
  schema attribute listed in `sampling.fields`. Custom (non-schema) dimensions are
  stamped as overlays *after* sampling, so they can't carry a proportional mix.
- CLI `generate_dev_personas.py --strategy <task>` applies the same mix (portions
  or weighted filters). `--task … --per-cell` still fills **grounding.toml** probe
  cells only — it does not read `persona_strategy.json`.

Playground turns on **Task default strategy** from this file (filters / mode /
allocation / portions locked to the file). Operators can turn that switch off to edit
filters themselves, then turn it back on to re-apply the task default.

### Ensuring pool coverage

`persona/datasets/matraix-persona-dev-sample/` is a small ~200-persona fixture for
smoke and local UI work. Narrow `dimensionFilters` (and stratified cells) often
undershoot it.

**When coverage fails**, do one of:

1. **Sample from production** — set `"pool"` to `persona/datasets/matraix-persona-1m`
   (or choose that pool in Playground), then Pull a cohort.
2. **Widen filters** — relax `dimensionFilters` / `sources` until the fixture (or 1M)
   has enough matches.
3. **Reuse a saved YAML dataset** — after a good pull, **Save as dataset…** writes
   `persona/datasets/<name>/` (listed under Dataset; sampling defaults to **All**).
4. **Synthesize a fill pool** — `generate_dev_personas.py --strategy <task>` (or
   Playground **Synthesize to fill this task**) writes
   `persona/datasets/generated-persona-dev-strategy-<task>/` (`source: synthetic`;
   no quality filter / dedup / calibration). Gitignored; listed in Dataset.

Playground / job launch **does not** invent personas at Pull time.

> **Not the same thing:** `persona/datasets/saved-cohorts/` stores **Save cohort**
> recipes / frozen id lists (`cohort.json`). It does not expand pool coverage by
> itself. See [Playground pools & cohorts](../../../docs/persona/README.md#playground-pools--cohorts).

Thin coverage raises an error with the same recovery hint.
