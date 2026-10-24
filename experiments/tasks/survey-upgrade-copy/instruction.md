# Upgrade prompt copy survey

## Your situation

You just hit a usage limit in **RelayDesk** and were shown an upgrade prompt.
Read the copy in `input/context.md` (it reflects the **{{ context_variant }}**
variant you were shown), then answer the questionnaire honestly as yourself.

## Your goal

Answer every question in `input/questionnaire.yaml` based on how that prompt
actually felt to you, given your real priorities and spending posture. Do not
invent claims that were not presented.

## Save your answers

Write your responses to `/app/output/survey_result.json` using this shape:

```json
{
  "answers": [
    { "questionId": "upgrade_intent", "response": 5 },
    { "questionId": "perceived_value", "response": 6 },
    { "questionId": "perceived_pressure", "response": 3 },
    { "questionId": "preferred_plan", "response": "team" }
  ]
}
```

## Rules

- Use the exact `questionId` values from `input/questionnaire.yaml`; do not rename
  or drop questions.
- Likert questions are integers on their stated scale; choice questions must use
  one of the listed options.
- Base your ratings only on the copy you were shown; keep them consistent with
  your persona's priorities.
- Finish after saving the completed JSON file.
