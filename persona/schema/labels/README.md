# Persona dimension label packs

Locale-specific **display overlays** for `persona/schema/dimensions.json`.
There is exactly one canonical dimension catalog — always English ids and
values. A label pack only changes what operators *see* in the Playground
(filter / stratify / cohort surfaces). Storage, sampling, filters, scoring, and
the Treiver keep using English codes; missing translations fall back to the
English strings at render time.

```
dimensions.json                      dimensions.labels.zh-Hans.json / zh-Hant.json
---------------                      ------------------------------
id: primary_language                 primary_language -> 主要语言
values: [Mandarin, English, ...]     Mandarin -> 普通话
```

## Layout

Committed packs currently include: `zh-Hans`, `zh-Hant`, `ja`, `ko`, `es`, `pt-BR`.

```
persona/schema/labels/
  build_labels.py                    # deterministic generator + validator
  dimensions.labels.<locale>.json    # generated packs (committed)
  sources/<locale>/
    meta.json                        # {"reviewStatus": "reviewed" | "machine-assisted"}
    dimensions.json                  # per-dimension {label, values} — no cross-dim sharing
    taxonomy.json                    # optional Layer-1/2 accordion titles (Background, …)
```

Each dimension owns its own translations. A shared English token such as
`None` is **not** copied across dimensions; translate it on `primary_language`
and on a skill dimension separately if both need a localized display string.

## Workflow

```bash
# regenerate one pack from its sources
python persona/schema/labels/build_labels.py --locale ko

# CI-style staleness check for every committed pack
python persona/schema/labels/build_labels.py --all --check
```

Rules (enforced by the generator and `tests/unit/matraix/test_dimension_label_packs.py`):

- every dimension id / value key in a pack must exist in `dimensions.json`;
- packs record the `sha256` of `dimensions.json` (`sourceHash`) — a schema
  change makes packs stale until regenerated;
- regeneration from unchanged sources is byte-identical;
- `reviewStatus` must be honest: `reviewed` only when a fluent speaker checked
  the pack, otherwise `machine-assisted`;
- untranslated entries are simply omitted — never pad with English copies or
  invented enum values.

Serving: the Playground backend exposes packs via
`GET /api/persona-pool/dimension-labels?locale=<code>`; the frontend overlays
them through `useDimensionLabels()` keyed off the active UI locale.
