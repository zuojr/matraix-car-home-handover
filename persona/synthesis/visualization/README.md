# Full DAG Visualization

This directory contains generated static visualizations for the Persona Full DAG:

- `full_dag_overview.html` — interactive node-link view of the full graph.
- `full_dag_publication.pdf` / `.png` — publication figure of the full DAG
  (all nodes and edges, one lane per category), for the paper.
- `persona_schema_chord.png` / `.pdf` — publication-quality two-ring chord
  diagram summarizing the schema at the taxonomy level.

## Generate

Run from the repository root:

```bash
uv run python persona/synthesis/scripts/render_graph_visualization.py
```

By default this reads:

```text
persona/synthesis/graph/full_dag.json
persona/schema/dimensions.json
```

and writes:

```text
persona/synthesis/visualization/full_dag_overview.html
```

To render a different graph or output path:

```bash
uv run python persona/synthesis/scripts/render_graph_visualization.py \
  --graph persona/synthesis/graph/full_dag.json \
  --schema persona/schema/dimensions.json \
  --out /tmp/full_dag_overview.html
```

## Open

For normal local review:

```bash
open persona/synthesis/visualization/full_dag_overview.html
```

If a browser or test harness blocks direct `file://` access, serve the repo over
local HTTP:

```bash
python -m http.server 8765
open http://localhost:8765/persona/synthesis/visualization/full_dag_overview.html
```

Stop the temporary server with `Ctrl-C`.

## Full DAG Publication Figure

`full_dag_publication.pdf` / `.png` is the static, publication-quality twin of
the interactive overview: every one of the 1,308 nodes and 6,999 directed
proposal edges, with the same layout semantics, palette, and lane order as
`full_dag_overview.html` — X follows `proposal_view.topological_order`, Y
groups nodes into one lane per schema category (44 lanes, ordered by mean
topological position). Node radius scales with the square root of directed
degree, edges are recessive gray beziers, and latent/helper nodes render at
lower opacity. `--node-alpha` / `--edge-alpha` tune the ink density.

Regenerate it from the repository root:

```bash
uv run python persona/synthesis/scripts/render_dag_publication.py
```

## Persona Schema Chord Diagram

`persona_schema_chord.png` / `.pdf` is a publication-quality two-ring chord
diagram of the schema, aligned to the official taxonomy table
(9 groups / 35 sub-categories / 1290 attributes):

- Inner ring: 35 sub-categories, coloured by their parent group.
- Chord ribbons: directed-proposal edges aggregated to the sub-category level.
- Outer ring: the 9 top-level groups spanning their sub-categories.

Regenerate it from the repository root:

```bash
uv run --extra viz python persona/synthesis/scripts/render_persona_schema_chord.py
```

Aggregation notes:

- Latent/helper graph nodes (18 nodes with no `category`) are excluded, so the
  figure covers exactly the 1,290 real persona attributes.
- The 8 `Developer: *` categories are merged into one `Developer/Coding`
  sub-category, matching the taxonomy table.
- `Demographic: Family` (1 attribute, no modeled edges) is omitted.
- Only sub-category pairs with at least `--threshold` aggregated edges
  (default 6) are drawn; weaker pairs are hidden to keep the diagram readable.

## What It Shows

The page embeds the full graph payload:

- 1,290 schema/emitted persona attributes
- 0 hidden persona attributes
- 18 latent/helper graph nodes
- 1,308 total graph nodes
- 6,999 directed proposal edges
- 44 category lanes

Layout semantics:

- X position follows `proposal_view.topological_order`.
- Y position groups nodes by category.
- Node size scales with directed degree.
- Latent/helper nodes render with lower opacity.
- Each node inspector labels the node as `attribute` or `latent/helper`.

Controls:

- Search by node id, label, category, or node type.
- Filter by category.
- Filter by minimum degree.
- Toggle hidden/helper nodes.
- Toggle edges.
- Drag to pan.
- Scroll to zoom.
- Hover or click a node to inspect id, label, category, node type, degree,
  value count, schema-attribute status, and emitted-attribute status.

## Update Policy

Do not hand-edit `full_dag_overview.html`. Regenerate it with
`render_graph_visualization.py` after changing `full_dag.json` or the
visualization code, then commit both the script change and the generated HTML.

Likewise, do not hand-edit `persona_schema_chord.png` / `.pdf` or
`full_dag_publication.pdf` / `.png`. Regenerate them with
`render_persona_schema_chord.py` / `render_dag_publication.py`, then commit both
the script change and the generated figures.
