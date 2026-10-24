# survey-upgrade-copy (SUT · survey)

**Hypothesis:** on an in-app upgrade prompt, social-proof copy raises upgrade
intent more than savings-framed or premium-framed copy, without increasing
perceived pressure.

## Contract

| Field | Value |
|-------|-------|
| `compareBy` | `system` (SUT) |
| `design` | `ab_n` (3 arms) |
| `armAssignment` | `shared` |
| Factor | `context_variant` — `social_proof` (baseline), `savings`, `premium` |
| Primary | `upgrade_intent` |
| Secondary | `perceived_value`, `preferred_plan` |
| Guardrail | `perceived_pressure` |

**Cohort (not part of the hypothesis):** stratified on `economic_motivation`
50/30/20 cost-sensitive / value-driven / premium-seeking
(`persona_strategy.json` → `dimensionFilters` + `allocation: proportional`).
That mix makes the primary OEC population-weighted; it is sampling design, not
the causal claim. Question ids stay stable across copy variants; only framing
text changes.

## Authoring

Full checklist:
[docs/application/experiment-task-guide.md](../../../docs/application/experiment-task-guide.md).
