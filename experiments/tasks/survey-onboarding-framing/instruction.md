# Onboarding experience survey

## Your situation

You have just finished a first-run onboarding for a new productivity app. Read
the framing in `input/context.md` (it reflects the **{{ context_variant }}**
variant you were shown), then answer the questionnaire honestly as yourself.

## Your goal

Answer every question in `input/questionnaire.yaml` based on how the onboarding
actually felt to you, given your real priorities and context. Do not invent
features or claims that were not presented.

## Save your answers

Write your responses to `/app/output/survey_result.json` using this shape:

```json
{
  "answers": [
    { "questionId": "onboarding_satisfaction", "response": 5 },
    { "questionId": "likelihood_to_continue", "response": 6 },
    { "questionId": "perceived_effort", "response": 3 },
    { "questionId": "preferred_next_step", "response": "invite_team" }
  ]
}
```

## Rules

- Use the exact `questionId` values from `input/questionnaire.yaml`; do not rename
  or drop questions.
- Likert questions are integers on their stated scale; choice questions must use
  one of the listed options.
- Base your ratings only on the framing you were shown; keep them consistent with
  your persona's priorities.
- Finish after saving the completed JSON file.
