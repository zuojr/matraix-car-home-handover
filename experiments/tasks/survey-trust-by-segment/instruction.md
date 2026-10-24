# Trust in AI recommendations survey

## Your situation

An app you use has started offering **AI-generated recommendations** (for
plans, content, and next actions). Read the short brief in `input/context.md`,
then answer the questionnaire honestly as yourself.

## Your goal

Answer every question in `input/questionnaire.yaml` based on how much you would
actually trust and act on these AI recommendations, given your real priorities
and spending posture.

## Save your answers

Write your responses to `/app/output/survey_result.json` using this shape:

```json
{
  "answers": [
    { "questionId": "trust_in_ai", "response": 5 },
    { "questionId": "adoption_intent", "response": 4 },
    { "questionId": "perceived_risk", "response": 3 },
    { "questionId": "recommended_channel", "response": "in_app" }
  ]
}
```

## Rules

- Use the exact `questionId` values from `input/questionnaire.yaml`.
- Likert questions are integers on their stated scale; the choice question must
  use one of the listed options.
- Answer as your persona would; let your priorities and spending posture shape
  how much you trust the recommendations.
- Finish after saving the completed JSON file.
