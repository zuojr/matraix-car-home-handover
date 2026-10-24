from __future__ import annotations

import subprocess
from pathlib import Path

from matraix.task_catalog import APPLICATION_TASK_METADATA


ROOT = Path(__file__).resolve().parents[2]


def _tracked_application_task_dirs() -> set[str]:
    """Git-tracked ``application/tasks/<dir>/task.toml`` folders only."""
    listed = subprocess.check_output(
        ["git", "ls-files", "application/tasks"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    dirs: set[str] = set()
    for relative in listed:
        parts = Path(relative).parts
        if (
            len(parts) >= 3
            and parts[0] == "application"
            and parts[1] == "tasks"
            and parts[-1] == "task.toml"
        ):
            dirs.add(parts[2])
    return dirs


def test_application_task_catalog_matches_shipped_task_dirs() -> None:
    catalog = set(APPLICATION_TASK_METADATA)
    on_disk = _tracked_application_task_dirs()

    assert catalog == on_disk, (
        "APPLICATION_TASK_METADATA must match shipped application/tasks dirs.\n"
        f"only in catalog: {sorted(catalog - on_disk)}\n"
        f"only on disk: {sorted(on_disk - catalog)}"
    )
