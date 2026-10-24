# Experiment task guide

How to author a **controlled experiment** task under `experiments/tasks/`.
This is separate from single-run application tasks
([task-guide.md](task-guide.md) / `application/tasks/`).

Experiments reuse Harbor / Playground launch and aggregation, but declare a
**factor space + metric contract** so the workbench can expand arms, share a
cohort (or contrast personas), and run a scorecard.

Contract schemas live in
[`experiments/task-spec/`](../../experiments/task-spec/README.md).
This page is the **checklist**: what to decide, what to put where, and what
breaks if you skip it.

---

## 1. Decide the experiment first

Answer these before creating files. Getting them wrong is the usual onboarding
failure mode.

### 1.1 What varies? (axis)

| You vary… | Set `compareBy` | Axis in UI | Cohort |
|-----------|-----------------|------------|--------|
| Product / copy / page / questionnaire framing | `system` | **SUT** | One shared cohort sees every arm |
| Who the person is (a persona attribute) | `persona` | **PUT** | One arm per persona level; environment stays fixed |

- **SUT** = System Under Test. Stimulus changes; people stay comparable.
- **PUT** = Persona Under Test. People change; stimulus is pinned in
  `constants[]`.

The workbench does **not** let operators flip `compareBy`. It is intrinsic to
the task.

### 1.2 How do levels combine? (`design`)

| `design` | Expansion | When to use |
|----------|-----------|-------------|
| `ab_n` | Baseline + one cell per non-baseline level (OFAT) | One factor, classic A/B/n |
| `full_factorial` | All level combinations | Interaction effects across factors |
| `fractional` | Orthogonal subset (2-level Taguchi OA; else falls back) | Many factors, fewer arms |

### 1.3 How are people assigned? (`armAssignment`, SUT only)

| Value | Meaning | Sample-size intuition |
|-------|---------|------------------------|
| `shared` (default) | Same personas run every arm (paired / within-subject) | `sampleSize` = people per arm; trials ≈ N × arms |
| `split` | Cohort partitioned across arms (between-subject) | `sampleSize` = total people across arms |

PUT is always `split`. Omitting `armAssignment` on PUT is fine.

### 1.4 What do you measure? (`metricContract`)

| Role | Job |
|------|-----|
| `primary` | OEC — the ship decision |
| `secondary` | Diagnostic / process |
| `guardrail` | Must-not-regress (effort, trust, risk, …) |

Keys must be **facet keys the verifier actually emits** (see §4). Every arm
must emit the **same** keys so the scorecard can align them.

---

## 2. Copy an exemplar

```text
experiments/tasks/
├── web-compare-options/           # SUT · web · A/B landing pages
├── survey-onboarding-framing/     # SUT · survey · framing A/B
├── survey-upgrade-copy/           # SUT · survey · copy A/B
└── survey-trust-by-segment/       # PUT · survey · persona contrast
```

| Goal | Copy |
|------|------|
| Landing / site A/B | `web-compare-options` |
| Survey question framing / copy (same people) | `survey-onboarding-framing` |
| Different persona segments, same instrument | `survey-trust-by-segment` |

There are no chatbot / os-app exemplars yet; factor vocabularies exist under
`experiments/task-spec/{chatbot,os-app}/` if you need to start from scratch.

Rename the folder to `experiments/tasks/<your-slug>/` (kebab-case).

---

## 3. Required files

```text
experiments/tasks/<your-slug>/
├── experiment.json          # REQUIRED — factor space + metricContract
├── persona_strategy.json    # REQUIRED — cohort eligibility + sampling
├── instruction.md           # REQUIRED — agent scenario (templates OK)
├── task.toml                # REQUIRED — Harbor env / timeouts / artifacts
├── input/                   # REQUIRED materials for the agent
│   ├── context.md           # almost always
│   ├── questionnaire.yaml   # survey
│   └── self_report_schema.yaml  # web (and others that fold user_feedback)
├── tests/
│   └── test.sh              # REQUIRED — calls the generic verifier
└── README.md                # recommended — hypothesis, arms, how to smoke
```

Unlike application tasks, experiment tasks **do not** need `reporting.json`.
They use the Experiments workbench scorecard instead.

Optional:

- `variants/<levelId>/expected.json` — only if a level has an objectively
  correct answer (correctness path; most behavioral experiments skip this).

---

## 4. `experiment.json` contract

Minimal shape (see `experiments/task-spec/schemas/experiment.schema.json`):

```json
{
  "schemaVersion": "1.0",
  "appType": "survey",
  "verifier": "survey_generic",
  "outputArtifact": "survey_result.json",
  "hypothesis": "One sentence: what you expect and for whom.",
  "compareBy": "system",
  "design": "ab_n",
  "armAssignment": "shared",
  "factors": [ /* … */ ],
  "constants": [],
  "signals": [],
  "metricContract": {
    "primary": ["…"],
    "secondary": ["…"],
    "guardrail": ["…"]
  }
}
```

### 4.1 Required fields

| Field | Values / notes |
|-------|----------------|
| `schemaVersion` | `"1.0"` |
| `appType` | `web` \| `survey` \| `chatbot` \| `os-app` |
| `verifier` | Matching `*_generic`, or `"custom"` + your own `tests/` |
| `compareBy` | `system` \| `persona` |
| `design` | `ab_n` \| `full_factorial` \| `fractional` |
| `factors` | Non-empty array |

Runtime load currently checks “file exists + JSON object + non-empty
`factors`”. Treat the schema as the **authoring contract** even when CI does
not enforce every field yet.

### 4.2 Factors

```json
{
  "id": "context_variant",
  "label": "Onboarding framing",
  "space": "system",
  "source": "stimulus",
  "baseline": "feature",
  "levels": [
    { "id": "feature", "label": "Feature-framed", "value": "feature" },
    { "id": "outcome", "label": "Outcome-framed", "value": "outcome" }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `space` | `system` → expands into design cells (SUT). `persona` → PUT contrast only |
| `source` | `stimulus` (injected params), `catalog` / `overlay` (persona dims) |
| `baseline` | Level id that is the control |
| `levels[].value` | Scalar shortcut (becomes a param), **or** `params: { … }` for multi-key |
| `levels[].label` | Shown in the UI / scorecard |

**SUT rule:** factors that change the environment use `space: "system"`.

**PUT rule:** the contrast attribute uses `space: "persona"`; pin the
environment with `constants[]` (same questionnaire / URL for every arm).

### 4.3 Stimulus injection

For every cell param **and** every constant, the experiment layer:

1. Substitutes `{{ param_name }}` in `instruction.md` and `input/context.md`
2. Exports `MATRIX_PARAM_<UPPER_NAME>` into the trial environment

Example: factor id / param `target_url` → `{{ target_url }}` and
`MATRIX_PARAM_TARGET_URL`.

Survey framing often selects a section of `context.md` with
`MATRIX_PARAM_CONTEXT_VARIANT` — keep **question ids identical** across
levels so arms stay comparable.

### 4.4 Signals vs survey question ids

| App type | How metrics appear |
|----------|--------------------|
| **Web** | Declare `signals[]` that map fields in `outputArtifact` → facet `key`s. Self-report keys from `input/self_report_schema.yaml` (e.g. `effort_rating`) are folded in automatically. |
| **Survey** | `signals: []` is normal. `survey_generic` emits one facet per `questionId` in `survey_result.json`. Put those **question ids** (and any self-report keys) into `metricContract`. |

Mismatch symptom: scorecard shows empty primary / “no comparisons”.

### 4.5 Verifier entry (`tests/test.sh`)

Point at the matching generic verifier under `experiments/task-spec/verifiers/`:

| `appType` | Script |
|-----------|--------|
| `web` | `web_generic.py` |
| `survey` | `survey_generic.py` |
| `chatbot` | `chatbot_generic.py` |
| `os-app` | `osapp_generic.py` |

Copy `tests/test.sh` from the nearest exemplar; set `EXPERIMENTS_TASK_DIR` the
same way. Default behavioral check: the `outputArtifact` exists.

---

## 5. `persona_strategy.json` contract

This is the **cohort contract** the configurator and gap checks read.

```json
{
  "schemaVersion": "1.0",
  "sources": [],
  "dimensionFilters": {
    "age_bracket": ["25-34", "35-44"],
    "region": ["North America", "Western Europe"]
  },
  "sampling": {
    "mode": "random",
    "sampleSize": 24
  }
}
```

### 5.1 Essentials

| Field | Notes |
|-------|-------|
| `schemaVersion` | `"1.0"` |
| `dimensionFilters` | Who is eligible. Values must exist in the persona catalog |
| `sampling.mode` | `random` \| `stratified` \| `single` \| `all` |
| `sampling.sampleSize` | People drawn (see armAssignment for trial count) |

Stratified extras: `fields`, `allocation` (`perCell` \| `proportional` \|
`equalTotal`), `perCell` / `portions` as required by allocation.

### 5.2 PUT alignment

For PUT, the contrast dimension (e.g. `economic_motivation`) must appear in:

1. `experiment.json` → factor `levels[].value` (exact catalog strings)
2. `persona_strategy.json` → `dimensionFilters` for the same dimension
   (eligibility; usually include baseline + treatment values)

The workbench blocks launch when the pool cannot cover the contract
(`contractGaps`). Prefer the 1M coreset for real cohorts; the checked-in
~200 sample is smoke-only.

### 5.3 Rejected legacy shapes

Do **not** use flat legacy keys (`defaultMode`, top-level `sampleSize`,
`stratifyFields`, …). Nest everything under `sampling` as above.

---

## 6. `task.toml` and materials

Mirror the nearest exemplar:

- **Survey** → `[environment].definition = "application/shared-survey-form"`
- **Web** → shared Playwright / browser definition + optional
  `[environment].local_compose` for variant sidecars
- `artifacts = ["/app/output"]` (usual Docker path)
- `[metadata].type` should match `appType` (`survey`, `web`, …)
- Tag with `"experiment"` so Runs can filter

`instruction.md` should state the persona’s job in first person / scenario
form and mention how the varying stimulus shows up (`{{ … }}`).

---

## 7. Onboarding checklist

Use this as a PR / self-review list:

1. **Hypothesis** written in one sentence (who, what changes, expected lift,
   what must not regress).
2. **`compareBy` / `design` / `armAssignment`** match the decision in §1.
3. **Factors** have a clear `baseline`; SUT vs PUT `space` is correct.
4. **PUT:** `constants[]` pin the environment; contrast values match catalog
   strings in `persona_strategy.json`.
5. **`metricContract` keys** match emitted facets (signals or survey
   `questionId`s + self-report).
6. **Templates / env** — every varying param is either `{{ name }}` or only
   consumed via `MATRIX_PARAM_*` (document which).
7. **Survey:** question ids stable across levels; only framing / copy /
   context differs.
8. **`tests/test.sh`** calls the correct `*_generic.py`.
9. **Pool coverage** — strategy filters have matches in the pool you will use.
10. **Smoke in UI** — Experiments → task → Configure → synthesize/draw cohort →
    launch a tiny run (e.g. 2–4 people) → Results / Analysis / Export.

CLI parity (optional):

```bash
matraix experiment list
matraix experiment show <experiment_id>
matraix experiment analyze <experiment_id> --format csv
```

---

## 8. Common failure modes

| Symptom | Likely cause |
|---------|--------------|
| Task missing from Experiments browser | No `experiment.json`, or not under `experiments/tasks/<slug>/` |
| Scorecard empty / no primary | `metricContract` keys ≠ emitted facet keys |
| Survey arms not comparable | Question ids changed between levels |
| Launch blocked on cohort gaps | Filters / PUT values not in the selected pool |
| PUT arms look like SUT | Forgot `space: "persona"` and/or `constants[]` |
| Trial count surprising | Misread `shared` (N×arms) vs `split` / PUT (N total) |
| Verifier fails immediately | `tests/test.sh` path / `EXPERIMENTS_TASK_DIR` wrong; missing artifact |

---

## 9. Where to go next

| Doc | Role |
|-----|------|
| [`experiments/README.md`](../../experiments/README.md) | Subsystem overview + layout |
| [`experiments/task-spec/README.md`](../../experiments/task-spec/README.md) | Schemas, signals, injection, verifiers |
| [`experiments/task-spec/schemas/experiment.schema.json`](../../experiments/task-spec/schemas/experiment.schema.json) | Field-level schema |
| Per-type vocab | `experiments/task-spec/{web,survey,chatbot,os-app}/README.md` |
| Shared facet vocabulary | [`application/task-spec/docs/shared-core-metrics.md`](../../application/task-spec/docs/shared-core-metrics.md) |
| [Submit artifacts (HF)](hf-experiment-artifacts.md) | Frozen cohort + trial artifacts (private dataset) |
| Single-run tasks (not experiments) | [task-guide.md](task-guide.md) |
