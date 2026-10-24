# Note to CSV cleanup (Linux)

MatrAIx **Linux desktop** computer-use task: turn a rough note into a
small CSV artifact and submit matching metadata in JSON.

Requires **`persona-computer-1`** with default **Docker** environment (Matraix Playground `Computer1`). No `USE_COMPUTER_API_KEY`.

```bash
uv sync --extra computer-1
export ANTHROPIC_API_KEY=...
uv run matraix run \
  -a persona-computer-1 \
  -m anthropic/claude-sonnet-4-6 \
  --ak persona_path=persona/datasets/matraix-persona-dev-sample/persona_0042.yaml \
  -p application/tasks/example-computer-use-linux_note-to-csv
```

## Smoke

Oracle:

```bash
uv run matraix run -p application/tasks/example-computer-use-linux_note-to-csv -a oracle
```

Persona agent (`persona-computer-1`): see command above.

## Output

- `/app/output/cleaned_list.csv`
- `/app/output/submission.json`

The verifier checks:

- the CSV header is `item,quantity,priority`
- the CSV has exactly three data rows
- the JSON metadata points to the CSV and records `rows_written = 3`
