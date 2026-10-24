# Explore the product and decide whether to sign up

## Your situation

You are looking for a tool for a realistic personal or work need. Read the
scenario brief in `input/context.md`, then browse the product's landing page and
decide, **as yourself**, whether you would actually sign up right now.

## Your goal

Open the landing page at **{{ target_url }}** and look it over the way you
naturally would when deciding whether a new product is worth trying. Then make a
genuine decision:

- If you would realistically create an account, click the page's signup call to
  action (the button that takes you to the signup page) and land on it.
- If you would not sign up right now, simply do not click it.

There is no right answer. Sign up **only** if you genuinely would; do not click
just because you are asked to look at the page.

## Constraints on your behavior

- Use only information visible on the live page at {{ target_url }}.
- Do not invent needs, requirements, or context not provided about you or shown
  on the page.
- Do not fill in real credentials, pay, or contact sales. Reaching the signup
  page (by clicking the call to action) is what counts as signing up here.
- Do not visit any third-party site.

## Record your decision

Save your decision to `/app/output/signup_decision.json`:

```json
{
  "action_taken": "<signed_up|left_without_signup>",
  "reached_signup_page": true,
  "decision_basis": "<price|features|value|trust|convenience|novelty|fit|other>",
  "decision_reason": "<why you did or did not sign up, in your own voice, grounded in the page>",
  "exploration_style": "<quick_pick|compared_multiple|deep_research|hesitant>",
  "task_source_url": "{{ target_url }}"
}
```

- `action_taken` is `signed_up` only if you actually clicked through to the
  signup page; otherwise `left_without_signup`.
- `reached_signup_page` must be `true` when `action_taken` is `signed_up`, and
  `false` otherwise.
- `decision_basis` is the single factor that most drove your decision.

## Termination criteria

- Make your browsing decision first, then save the completed JSON file.
- Keep `decision_reason` faithful to what you actually saw on the page.
- Finish after saving the file (and your self-report, if requested).

## Success judgment

The task is successful when the saved JSON follows the required structure,
records `{{ target_url }}` as the source, and reports an internally consistent
decision (`action_taken`, `reached_signup_page`, and `decision_basis` agree with
your `decision_reason`).
