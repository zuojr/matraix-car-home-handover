"""CLI --strategy must keep declared mix (portions / weighted filters)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "persona" / "scripts" / "generate_dev_personas.py"


@pytest.fixture(scope="module")
def gen_cli():
    import sys

    src = str(REPO / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    spec = importlib.util.spec_from_file_location("generate_dev_personas", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_strategy_keeps_explicit_portions(gen_cli, tmp_path: Path) -> None:
    path = tmp_path / "persona_strategy.json"
    path.write_text(
        """
        {
          "dimensionFilters": {
            "economic_motivation": ["Cost-sensitive", "Premium-seeking"]
          },
          "sampling": {
            "mode": "stratified",
            "fields": ["economic_motivation"],
            "allocation": "proportional",
            "sampleSize": 20,
            "portions": {
              "economic_motivation": {"Cost-sensitive": 0.7, "Premium-seeking": 0.3}
            }
          }
        }
        """,
        encoding="utf-8",
    )
    loaded = gen_cli._load_strategy(path)
    assert loaded["sampling"]["portions"] == {
        "economic_motivation": {"Cost-sensitive": 0.7, "Premium-seeking": 0.3}
    }


def test_load_strategy_derives_portions_from_weighted_filters(gen_cli, tmp_path: Path) -> None:
    path = tmp_path / "persona_strategy.json"
    path.write_text(
        """
        {
          "dimensionFilters": {
            "economic_motivation": {"Cost-sensitive": 0.4, "Value-driven": 0.35, "Premium-seeking": 0.25}
          },
          "sampling": {
            "mode": "stratified",
            "fields": ["economic_motivation"],
            "allocation": "proportional",
            "sampleSize": 20
          }
        }
        """,
        encoding="utf-8",
    )
    loaded = gen_cli._load_strategy(path)
    assert loaded["dimensionFilters"]["economic_motivation"] == [
        "Cost-sensitive",
        "Value-driven",
        "Premium-seeking",
    ]
    assert loaded["sampling"]["portions"] == {
        "economic_motivation": {
            "Cost-sensitive": 0.4,
            "Value-driven": 0.35,
            "Premium-seeking": 0.25,
        }
    }
