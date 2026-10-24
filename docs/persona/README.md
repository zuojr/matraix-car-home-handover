# Persona

MatrAIx personas use a 1,290-dimensional schema for human profiles, plus
attribute extraction pipelines, grounding validation, and a public 1 million
row coreset for persona-aware evaluation.

> **Pipeline internals:** for how the corpus is actually built end to end — curation, human extraction, synthetic generation, and the post-processing chain (quality filter → deduplication → unified dataset → 1M coreset → statistics) — see [Persona Pipeline](pipeline.md).

## Overview

A **persona** is a rich structured profile of a person represented as 1,290 categorical attributes across core demographics (age, region, gender identity, urbanicity), professional domains, skills, interests, values, and psychological traits. The MatrAIx Persona system enables:

- **Schema**: A comprehensive 1,290-dimension taxonomy organized in `persona/schema/dimensions.json`
- **Extraction**: Automatic attribute extraction from free-text descriptions using a hybrid regex + LLM pipeline (Treiver)
- **Validation**: Grounding tasks that verify persona-aware AI behavior through structured probes
- **Public dataset**: The MatrAIx Persona 1M — a balanced, quality-filtered, deduplicated coreset of 1,000,000 personas (60% human-grounded, 40% synthetic)

## The 1,290-Dimension Schema

The persona schema defines 1,290 categorical dimensions organized hierarchically:

- **Core demographics**: age brackets, region, gender identity, urbanicity
- **Professional domains**: 143 technical proficiencies (programming, data science, cloud platforms, etc.)
- **Skills and expertise**: communication, leadership, analytical reasoning across generic scale values
- **Interests and values**: hobbies, causes, preferences
- **Psychological traits**: values alignment, personality dimensions

Each dimension has specific categorical values (e.g., age: "Under 5", "5-12", ..., "85+"; proficiency: "Expert", "Proficient", "Intermediate", "Familiar", "No knowledge"). A persona assigns exactly one value per dimension, though extraction may discover only a subset of assignments from source text.

See `../../persona/schema/` for the complete taxonomy, calibration targets, and category mappings.

## Attribute Extraction: Treiver

The **Treiver** (trait-retriever) turns a free-text description of a person into structured `(dimension_id, value)` attributes from the schema. It's a lightweight RAG pipeline with two stages:

```
prompt ──▶ [1] regex retrieval ──▶ candidate dimensions ──▶ [2] LLM judge ──▶ attributes
                │                                               │
                └──────────────── regex attributes ─────────────┘
```

### Stage 1: Regex Retrieval
For each dimension, match the prompt against patterns built from its allowed values plus aliases. A dimension that matches becomes a *candidate*. This stage:
- Runs **fully offline**, deterministic, no API key required
- Applies **topic gating** for generic dimensions: "expert" alone doesn't reveal *what*, so 143+ "Proficient/Expert" dimensions also require the topic (e.g., "Data science") to match
- Outputs high-precision, low-recall candidates
- Is usable standalone for deterministic attribute extraction

### Stage 2: LLM Judge
Claude (with structured outputs) sees the prompt and only the candidate dimensions with their allowed values. For each candidate, it:
- Picks the single best value or returns `null` if unsupported
- Quotes evidence from the prompt
- Rates confidence (e.g., "high", "medium", "low")

Both stages emit records with `(dimension_id, value, evidence, method, confidence)` fields, feeding directly into extraction-quality reporting.

### Usage

Python:
```python
from persona.extraction import Treiver

t = Treiver()  # loads the bundled schema

# Stage 1 only — offline, deterministic:
result = t.match("a retired nurse in rural Kentucky")
for a in result.attributes:
    print(a.dimension_id, "=", a.value, f"[{a.method} {a.confidence}]")

# Stages 1 + 2 — with Claude judge:
result = t.match("a retired nurse in rural Kentucky", use_llm=True)
```

Command line:
```bash
python -m persona.extraction "a retired nurse in rural Kentucky, born 1950"
python -m persona.extraction --llm "senior python developer who loves astronomy"
echo "young woman, expert in data science" | python -m persona.extraction --json
```

The extraction module (`persona/extraction/`) contains:
- `schema.py` — load and index `dimensions.json`
- `regex_matcher.py` — regex retrieval and topic gating
- `embed_retriever.py` — semantic retrieval (local embeddings, optional)
- `llm_judge.py` — LLM judge with structured outputs
- `treiver.py` — orchestrator, merges regex and LLM results
- `__main__.py` — CLI interface

Implementation: `../../persona/extraction/` (`treiver.py`, `llm_judge.py`, `regex_matcher.py`).

## Curation and Data Sources

The 1M coreset combines multiple human-grounded sources:

- **Wikipedia extraction** (323,438 rows) — calibrated sample from 1.9M extracted profiles
- **Amazon Reviews 2023** (97,915 rows) — all retained profiles from review extraction
- **Stack Overflow survey** (113,120 rows) — all retained respondent profiles
- **GSS / World Values Survey** (63,532 rows) — mapped survey respondents
- **PRISM Alignment** (1,487 rows) — aligned human interviews
- **Real Human Survey** (508 rows) — direct respondent collection
- **Full-DAG synthetic** (400,000 rows) — calibrated sample from 8.4B-row synthetic pool

Human-grounded means derived from a real profile, history, or survey record. It does **not** mean every extracted attribute is a verified fact—model extraction can contain errors, and survey mappings depend on crosswalk quality.

Curation pipeline notes, schema decisions, and attribute-pool construction live in `../../persona/curation/`.

## Public Coreset: MatrAIx Persona 1M

A production-ready, balanced, deterministically curated 1,000,000-row coreset available on Hugging Face: [`MatrAIx2026/MatrAIx_Persona_1M_Public_Release`](https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release).

### Contents

Each row contains:
- **Provenance**: source, source row index, source record ID
- **Attributes**: 1,290 categorical attributes (packed as a 645-byte vector)
- **Missing values**: bitmap for null attributes (never imputed)
- **Descriptions**: natural-language text (only for human-grounded personas)
- **Grounding**: sparse evidence, confidence rating, extraction method
- **Metadata**: source-specific context

Parquet files are 10 shards of 100K rows each, compressed with Zstandard.

### Calibration

The coreset uses constrained, without-replacement calibration to balance marginal targets:
1. Apply upstream contradiction filter and 0.95 MinHash deduplication
2. Include all rows from five smaller sources (PRISM, GSS, Survey, Stack Overflow, Amazon)
3. Calibrate Wikipedia against global marginal targets
4. Compute synthetic residual targets so synthetic rows compensate for missing human coverage
5. Deterministic exponential-race sampling ensures reproducibility and input-order independence

Calibration targets for `age_bracket`, `region`, `gender_identity`, and `urbanicity` are grounded in UN World Population Prospects 2024 and World Bank data. Missing values remain missing—**no imputation**. The achieved sample may differ slightly from expected margins due to missing attributes and incompatible constraints; `audit.json` documents achieved vs. target distributions and any infeasibility.

### Setup and Usage

**Recommended** for Playground cohorts, task-strategy coverage, and multi-persona
jobs. The checked-in `matraix-persona-dev-sample` (~200) is smoke-only and often
undershoots narrow filters.

Set up locally:
```bash
# Recommended: download into the repo (Playground auto-discovers this path)
huggingface-cli download MatrAIx2026/MatrAIx_Persona_1M_Public_Release \
  --repo-type dataset --local-dir persona/datasets/matraix-persona-1m/release

# Or point at an external mirror
export MATRIX_PERSONA_1M_DIR=/path/to/MatrAIx_Persona_1M_Public_Release
```

The `MATRIX_PERSONA_1M_DIR` target must contain `data/persona-1m-*.parquet` and `persona_codes.schema.json`. Under `persona/datasets/matraix-persona-1m/`, `release/` holds the Parquet source (shown in the Dataset dropdown as `matraix-persona-1m`), `indexes/` holds the inverted postings for fast filtered/stratified sampling, and `cohorts/` is a local launch cache (not listed in the dropdown) where sampling writes cohort YAML for Matraix Playground to run.

Sampling indexes (`postings.sqlite` + `manifest.json`, ~2.5GB) ship in the public
release next to `release/` — keep them for fast stratified sampling. Rebuild
locally only if you change the Parquet shards:

```bash
PYTHONPATH=.:application/playground:src:environment/runtime:packages/playground/src \
  .venv/bin/python -m backend.service.build_persona_1m_indexes   # --enrich-source to refresh source postings only
```

In Playground:
1. Dataset → `matraix-persona-1m` (`All` is disabled on the full 1M root — sample a cohort instead)
2. Random or stratified sampling → up to 10,000 rows
3. Optional: **Save as dataset…** promotes a cohort to `persona/datasets/<name>/` so it appears under Dataset for reuse across tasks (sampling defaults to **All**)

The index is used automatically when present; Parquet is scanned if not.

## Playground pools & cohorts

Use this when choosing a Dataset, pulling a cohort, or deciding what is safe to commit.

### Dataset picker (what you select)

| Kind | How it appears | Typical path | Notes |
|------|----------------|--------------|--------|
| Production 1M | `matraix-persona-1m` | `persona/datasets/matraix-persona-1m/` | **Recommended** for real work; Parquet + indexes; **All** disabled on the root |
| Dev sample | `matraix-persona-dev-sample` | `persona/datasets/matraix-persona-dev-sample/` | Checked-in ~200 smoke fixture only |
| Generated | `generated-persona-dev-…` | `persona/datasets/generated-persona-dev-*/` | Full-DAG synthetic YAML; **gitignored** |
| Saved dataset | your slug | `persona/datasets/<name>/` | From **Save as dataset…**; UI defaults sampling to **All** |

Launch caches under `<dataset>/cohorts/` are **not** listed in Dataset.

### What gets written on disk

| Artifact | When | Path | In git? |
|----------|------|------|---------|
| Launch cache | **Pull cohort** from 1M, or a local sample larger than the UI id cap | `<source-dataset>/cohorts/cohort-<digest>/` | No |
| Saved dataset | **Save as dataset…** after a pull | `persona/datasets/<name>/` (`manifest.kind = saved-persona-dataset`) | No (local unless you force-add) |
| Saved cohort recipe | **Save cohort** (recipe / frozen ids) | `persona/datasets/saved-cohorts/<id>/cohort.json` | No |
| Generated pool | Generation tab or `generate_dev_personas.py` | `persona/datasets/generated-persona-dev-*/` | No |

**Do not confuse** `saved-cohorts/` (filter recipe / frozen id list) with **Save as dataset** (a real YAML pool in the Dataset dropdown).

### Sampling modes (short)

| Mode | Use when |
|------|----------|
| **Quick** | Pick one persona by hand |
| **Random** / **Stratified** | Draw a subset (required on the 1M root) |
| **All** | Run every persona in the selected dataset — default for **saved** datasets |

After switching to a saved dataset you still confirm with **Select all** (or Pull) before launch.

## Grounding and Validation Tasks

Persona-adherence probes live under `persona/validation/tasks/`, with runners
and reporting helpers in `persona/validation/scripts/`. For product scenarios
(survey, chat, web, computer-use), use `../application/tasks/`.

## Grounding Reporting

After a multi-persona Matraix Playground job completes:
```bash
uv run python persona/reporting/eval_grounding_job.py jobs/<job_name> \
  --meta configs/jobs/persona-job-recipe/<name>.meta.json
```

Outputs `persona_grounding_report.json` with:
- `dim_grounding_mean` — per-dimension probe success rate
- `pass_rate` — share of trials that passed validation
- `counterfactual_rate` — share of trials where the agent's answer leaked ungrounded bias

The `--meta` sidecar is auto-generated by `persona/scripts/generate_persona_job.py`.

## Sampling and Jobs

### Production Sampling: The 1M Pool
**Recommended default.** Use `persona/datasets/matraix-persona-1m` for Playground
and job launches that need real coverage. This is the canonical public coreset;
prefer it over the ~200-persona smoke fixture.

### Local synthetic pools

Sample Full-DAG personas for Playground experiments. Output appears in the
Dataset picker and is **gitignored**. Playground **Generation** and
`generate_dev_personas.py` share the same path.

```bash
uv run python persona/scripts/generate_dev_personas.py
# → persona/datasets/generated-persona-dev-2000/
```

Each YAML is `source: synthetic` from `persona/synthesis/graph/full_dag.json`.
This is a raw Full-DAG sample — it does **not** run quality filter, dedup, or
calibration (those belong to the published
[`matraix-persona-1m`](pipeline.md#1m-coreset) coreset).

Custom dimensions (not in the persona schema) use
`--overlay id[:label]=v1,v2`. IDs must start with a letter, use only letters /
numbers / underscores, and must not collide with an existing schema dimension.
Schema `--filter` values pin the DAG; overlay values are applied after sampling.

After Generate, Dataset switches to the new pool (it does **not** auto-select
the draw as the launch cohort). If **Task default** is on and Pull cannot cover
`persona_strategy.json`, **Synthesize to fill this task** (CLI: `--strategy`)
fills those cells, including any declared mix (`sampling.portions` or weighted
`dimensionFilters`). `--task … --per-cell` is a different path: grounding.toml
probe cells only.

### Playground Generation (Independent / Contrast)

Three sampling modes (hover the UI tabs for tooltips):

| UI | CLI | Meaning |
|----|-----|---------|
| **Random** | `--count N` | N personas per written dataset (uniform over selected filter cells when filters are set) |
| **By combo** | `--per-cell N` | N personas per selected filter combination |
| **By share** | `--sample-size N` | Allocate N from per-dimension shares (equal unless you set weights) |

**N is per dataset.** Contrast copies reuse one shared draw, so every contrast
dataset has the same size. UI and CLI show **one progress bar per dataset**.

Two filter workspaces:

- **Independent** — one mix (`--filter`; By share weights via `--marginal`).
- **Contrast** — optional shared filters (`--contrast-filter` /
  `--contrast-marginal`) plus **contrast attributes** (`--contrast`). Writes the
  complementary **base-value** pool plus one dataset per selected value
  combination. Labels look like `Contrast · Brand=Low`. After Generate, Dataset
  selects the base-value pool first.

Invalid schema contrast stamps (Full-DAG) error out without resampling; custom
overlay stamps skip the DAG check.

```bash
# Independent
uv run python persona/scripts/generate_dev_personas.py \
  --count 100 \
  --filter age_bracket=25-34

# Contrast (shared filters optional)
uv run python persona/scripts/generate_dev_personas.py \
  --count 100 \
  --overlay brand_trust:Brand=High,Low \
  --contrast brand_trust=High

# Independent + Contrast (By share with weights)
uv run python persona/scripts/generate_dev_personas.py \
  --sample-size 100 \
  --filter gender_identity=Man,Woman \
  --marginal gender_identity=Man:70,Woman:30 \
  --contrast-filter age_bracket=25-34 \
  --overlay brand_trust:Brand=High,Low \
  --contrast brand_trust=High

# Clone an existing pool into contrast copies
uv run python persona/scripts/generate_dev_personas.py \
  --contrast-from persona/datasets/generated-persona-dev-200 \
  --contrast brand_trust=High
```

Also useful: `--strategy` (task `persona_strategy.json`, including target mix),
`--task … --per-cell` (grounding.toml cells), `--stratify`,
`--contrast-dim` / `--contrast-value` (single-arm shorthand). Defaults:
`--count` 2000 (max 5000).

```bash
# Task-plan fill (honors persona_strategy.json mix)
uv run python persona/scripts/generate_dev_personas.py \
  --strategy application/tasks/example-survey_product-feedback
```

### Job Generation
Create a Matraix Playground job YAML from a task and persona pool by passing an
application or validation task path to `persona/scripts/generate_persona_job.py`.

This reads `grounding.toml` to sample stratified cohorts and filter on
confounders when present. Use `--controlled-probe` for anchor-based cohorts
(default for catalog tasks); `--no-controlled-probe` to disable.

See scripts under `../../persona/scripts/` for full options.

## Docker Integration

Persona bench tasks using Claude Code (`persona-claude-code` agents) pull install scripts from `../environment/docker-snippets/install-claude-code.sh`. After editing this file or adding a Claude Code task, sync copies to task Dockerfiles:

```bash
python scripts/sync_docker_snippets.py --write
```

## Post-Processing and Deduplication

The 1M coreset was built through a multi-stage post-processing pipeline:

- **Contradiction detection** — detects logically inconsistent attributes
- **0.95 MinHash deduplication** — removes near-duplicates before calibration
- **Quality filtering** — enforces consistency and coverage thresholds
- **Unified dataset construction** — merges all sources and applies deduplication
- **Calibration and sampling** — balances marginals and performs deterministic selection

Implementation and audit tools are in `../../persona/post_process/`. Each stage produces detailed logs and diagnostics; see [Persona Pipeline → 1M coreset](pipeline.md#1m-coreset) for the full build process and reproducibility notes.

## Project Layout

```
persona/
├── schema/                          # 1,290-dimension taxonomy (dimensions.json)
├── extraction/                      # Treiver: regex + LLM attribute extraction
├── curation/                        # Source pipelines, schema decisions, attribute pool
│   ├── attribute_pool/              # Dimension construction and validation
│   └── existing_data/               # Wikipedia, Amazon, survey processing
├── validation/                      # Persona-adherence validation probes
│   ├── tasks/                       # Probe tasks
│   └── scripts/                     # Matrix runners and reporting helpers
├── scripts/                         # Job generation and persona sampling
│   ├── generate_dev_personas.py     # Synthetic YAML pool (same generate path as Playground)
│   └── generate_persona_job.py      # Matraix Playground job YAML from task + pool
├── reporting/                       # Grounding evaluation
│   └── eval_grounding_job.py        # Aggregate job-level metrics
├── datasets/
│   ├── matraix-persona-dev-sample/  # Checked-in ~200 fixture
│   ├── matraix-persona-1m/          # Public 1M (release/ + indexes/ + cohorts/ cache)
│   ├── generated-persona-dev-*/     # Local synthetic YAML (gitignored)
│   ├── <saved-name>/                # Save as dataset… YAML pools (local)
│   └── saved-cohorts/               # Save cohort recipes / frozen ids (gitignored)
└── post_process/                    # Build pipeline: dedup, quality, calibration
    ├── coreset_1m/                  # 1M build, calibration, audit
    ├── deduplication/               # MinHash + contradiction detection
    ├── quality_filter/              # Consistency and coverage gates
    └── dataset_statistics/          # Marginal audits
```

## Quick Start

**Extract attributes from a person description:**
```python
from persona.extraction import Treiver
t = Treiver()
result = t.match("senior software engineer in Silicon Valley with ML expertise")
```

**Sample synthetic personas for Playground:**
```bash
uv run python persona/scripts/generate_dev_personas.py \
  --overlay brand_trust:Brand=High,Low \
  --contrast brand_trust=High
# Dataset picks the base-value pool (Contrast · Brand=Low)
```

**Launch a grounding evaluation:**
```bash
uv run matraix run -a persona-claude-code \
  --ak persona_path=persona/datasets/matraix-persona-1m/persona_0001.yaml \
  -p persona/validation/tasks/probe-survey_register
```

**Aggregate results:**
```bash
uv run python persona/reporting/eval_grounding_job.py jobs/my_job \
  --meta configs/jobs/persona-job-recipe/my_job.meta.json
```

For more details, see READMEs and docstrings under `persona/`.

## Related

| Doc | Role |
|-----|------|
| [Handbook](../README.md) | Docs home |
| [Playground pools & cohorts](#playground-pools--cohorts) | Dataset vs launch cache vs saved |
| [Persona pipeline](pipeline.md) | Curation → coreset build |
| [Validation](validation.md) | Persona-adherence probes |
| [Large-scale runs](../environment/large-scale-runs.md) | Multi-persona jobs |
| [Quickstart](../quickstart.md) | Run tasks with personas |
| [Application](../application/README.md) | Product scenarios |
