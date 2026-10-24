# survey-trust-by-segment (PUT · survey)

**Hypothesis:** among working-age, digitally comfortable users in North America
and Western Europe, economic motivation shifts how much people trust
AI-generated recommendations: for the **identical** questionnaire,
premium-seeking users report higher trust and adoption intent than
cost-sensitive users.

## Contract

| Field | Value |
|-------|-------|
| `compareBy` | `persona` (PUT) |
| `design` | `ab_n` |
| Factor | `economic_motivation` (`space: persona`, `source: catalog`) — `Cost-sensitive` (baseline) vs `Premium-seeking` |
| Constants | `questionnaire_variant = standard` (environment pinned) |
| Primary | `trust_in_ai` |
| Secondary | `adoption_intent`, `recommended_channel` |
| Guardrail | `perceived_risk` |

PUT arms always use split assignment (different people per level). Level
`value`s must match catalog strings **and** appear in
`persona_strategy.json` → `dimensionFilters.economic_motivation`.

## Authoring

Copy this for other persona-contrast surveys. Full checklist:
[docs/application/experiment-task-guide.md](../../../docs/application/experiment-task-guide.md)
(especially §1.1 PUT and §5.2 PUT alignment).
