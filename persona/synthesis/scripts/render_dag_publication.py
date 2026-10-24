#!/usr/bin/env python3
"""Render the publication figure of the Persona Full DAG (vector PDF + PNG).

The figure is the static, print-quality twin of the interactive
``full_dag_overview.html``: same layout semantics, same palette, same lane
order.

- X position follows ``proposal_view.topological_order``.
- Y position groups nodes into one lane per schema category, lanes ordered by
  the category's mean topological position (exactly like the HTML view).
- Node radius scales with the square root of directed degree; latent/helper
  nodes render at lower opacity.
- Edges are cubic beziers in a recessive gray.

Run from the repository root:

    uv run python persona/synthesis/scripts/render_dag_publication.py

Writes ``full_dag_publication.pdf`` and ``full_dag_publication.png`` into
``persona/synthesis/visualization/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.font_manager
import matplotlib.pyplot as plt
from matplotlib.collections import PathCollection
from matplotlib.patches import FancyBboxPatch
from matplotlib.path import Path as MplPath

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GRAPH_PATH = REPO_ROOT / "persona" / "synthesis" / "graph" / "full_dag.json"
DEFAULT_OUT_DIR = REPO_ROOT / "persona" / "synthesis" / "visualization"

# Same 20-colour palette as render_graph_visualization.py, assigned to lanes in
# the same order, so the PDF matches the interactive HTML view.
PALETTE = [
    "#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ca8a04",
    "#0891b2", "#db2777", "#4f46e5", "#059669", "#ea580c",
    "#7c3aed", "#0f766e", "#be123c", "#65a30d", "#0284c7",
    "#a21caf", "#b45309", "#047857", "#4338ca", "#c2410c",
]

HELPER_CATEGORY = "Uncategorized"
HELPER_LABEL = "Latent / helper"

INK = "#000000"
EDGE_COLOR = "#59677C"
LANE_RULE = "#97A3B3"
LEGEND_BORDER = "#D7DEE8"


def _use_inter_font() -> None:
    """Register the bundled Inter font and make it the default, if present."""
    inter_path = REPO_ROOT / "persona" / "schema" / "_fonts" / "Inter-Variable.ttf"
    if inter_path.exists():
        try:
            matplotlib.font_manager.fontManager.addfont(str(inter_path))
            name = matplotlib.font_manager.FontProperties(
                fname=str(inter_path)).get_name()
            plt.rcParams["font.family"] = name
        except Exception:
            pass


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def _stable_jitter(node_id: str) -> float:
    """Deterministic jitter in [-0.5, 0.5), same recipe as the HTML view."""
    digest = hashlib.sha1(node_id.encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) % 1000) / 999 - 0.5


def render(
    graph_path: Path,
    out_dir: Path,
    *,
    node_alpha: float = 0.78,
    edge_alpha: float = 0.045,
) -> dict:
    _use_inter_font()
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = graph["nodes"]
    edges = graph["directed_proposal_edges"]
    order = graph["proposal_view"]["topological_order"]
    topo = {node_id: i for i, node_id in enumerate(order)}

    def category(node: dict) -> str:
        return node.get("category") or HELPER_CATEGORY

    # Lane order: mean topological position, ties by name — as in the HTML.
    categories = Counter(category(n) for n in nodes)
    avg_topo = {}
    for cat in categories:
        positions = [
            topo[n["id"]] for n in nodes
            if category(n) == cat and n["id"] in topo
        ]
        avg_topo[cat] = sum(positions) / len(positions) if positions else 0
    lane_order = sorted(categories, key=lambda cat: (avg_topo[cat], cat))
    lane_index = {cat: i for i, cat in enumerate(lane_order)}
    lane_color = {cat: PALETTE[i % len(PALETTE)] for i, cat in enumerate(lane_order)}
    n_lanes = len(lane_order)

    degree = Counter()
    for edge in edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    max_degree = max(degree.values())

    denom = max(1, len(order) - 1)
    xy: dict[str, tuple[float, float]] = {}
    for node in nodes:
        node_id = node["id"]
        lane = lane_index[category(node)]
        x = topo.get(node_id, len(topo)) / denom
        # Lanes count downward from the top; jitter stays inside the lane.
        y = n_lanes - 1 - lane + _stable_jitter(node_id) * 0.47
        xy[node_id] = (x, y)

    fig_w, fig_h = 11.0, 7.0
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.subplots_adjust(left=0.216, right=0.994, top=0.988, bottom=0.015)
    ax.set_xlim(-0.01, 1.01)
    ax.set_ylim(-0.6, n_lanes - 0.3)
    ax.axis("off")

    # Recessive lane rules, as in the HTML view.
    for cat in lane_order:
        y = n_lanes - 1 - lane_index[cat]
        ax.axhline(y, color=LANE_RULE, alpha=0.22, linewidth=0.46, zorder=0)

    # Edges: cubic beziers in one recessive gray.
    paths = []
    for edge in edges:
        source, target = edge["source"], edge["target"]
        if source not in xy or target not in xy:
            continue
        (x0, y0), (x1, y1) = xy[source], xy[target]
        mx = (x0 + x1) / 2
        paths.append(MplPath(
            [(x0, y0), (mx, y0), (mx, y1), (x1, y1)],
            [MplPath.MOVETO, MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4],
        ))
    ax.add_collection(PathCollection(
        paths, facecolors="none", edgecolors=EDGE_COLOR,
        linewidths=0.37, alpha=edge_alpha, zorder=1,
    ))

    # Nodes, low degree first so hubs stay on top. Radii follow the HTML
    # (2.2 + 6.2 * sqrt(d / dmax) canvas px), rescaled to the page.
    plot_nodes = sorted(nodes, key=lambda n: degree[n["id"]])
    xs = [xy[n["id"]][0] for n in plot_nodes]
    ys = [xy[n["id"]][1] for n in plot_nodes]
    sizes = [
        (2 * (1.2 + 3.35 * (degree[n["id"]] / max_degree) ** 0.5)) ** 2
        for n in plot_nodes
    ]
    colors = [lane_color[category(n)] for n in plot_nodes]
    alphas = [
        node_alpha if n.get("category") else node_alpha * 0.55
        for n in plot_nodes
    ]
    ax.scatter(xs, ys, s=sizes, c=colors, alpha=alphas, linewidths=0, zorder=2)

    # Lane labels in the left margin.
    for cat in lane_order:
        y = n_lanes - 1 - lane_index[cat]
        label = HELPER_LABEL if cat == HELPER_CATEGORY else cat
        ax.annotate(
            label, xy=(0, y), xycoords=("axes fraction", "data"),
            xytext=(-5, 0), textcoords="offset points",
            ha="right", va="center", fontsize=9.8, color=INK,
        )

    # Degree legend box, top-right, over the empty end of the top lane.
    box_x0, box_x1 = 0.750, 0.995
    box_y0, box_y1 = 0.946, 0.998
    ax.add_patch(FancyBboxPatch(
        (box_x0, box_y0), box_x1 - box_x0, box_y1 - box_y0,
        transform=ax.transAxes, boxstyle="round,pad=0,rounding_size=0.006",
        facecolor="white", edgecolor=LEGEND_BORDER, linewidth=0.7, zorder=4,
    ))
    key_y = (box_y0 + box_y1) / 2
    ax.text(box_x0 + 0.016, key_y, "degree", transform=ax.transAxes,
            ha="left", va="center", fontsize=10.0, color=INK, zorder=5)
    for x, d, label_dx in [(0.836, 10, 5.0), (0.883, 100, 6.0), (0.944, 400, 8.0)]:
        ax.scatter(
            [x], [key_y], transform=ax.transAxes,
            s=[(2 * (1.2 + 3.35 * (d / max_degree) ** 0.5)) ** 2],
            facecolors="none", edgecolors=INK, linewidths=0.6, zorder=5,
        )
        ax.annotate(str(d), xy=(x, key_y), xycoords=ax.transAxes,
                    xytext=(label_dx, 0), textcoords="offset points",
                    ha="left", va="center", fontsize=9.3, color=INK, zorder=5)

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "full_dag_publication.pdf"
    png_path = out_dir / "full_dag_publication.png"
    fig.savefig(pdf_path)
    fig.savefig(png_path, dpi=300)
    plt.close(fig)
    return {
        "pdf": _display_path(pdf_path),
        "png": _display_path(png_path),
        "nodes": len(nodes),
        "edges": len(edges),
        "lanes": n_lanes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--node-alpha", type=float, default=0.78)
    parser.add_argument("--edge-alpha", type=float, default=0.045)
    args = parser.parse_args()
    summary = render(
        args.graph, args.out_dir,
        node_alpha=args.node_alpha, edge_alpha=args.edge_alpha,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
