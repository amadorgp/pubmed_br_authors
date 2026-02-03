"""
10_snapshot_project_structure.py

Purpose
-------
Generate a reproducible snapshot of the project structure (folders + files)
for documentation and onboarding.

Output
------
docs/project_structure.md

Notes
-----
- Ignores virtual environments and git internals.
- Safe to run anytime; output is deterministic (sorted).
"""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".vscode",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Snapshot project folder/file structure into docs.")
    p.add_argument("--project-root", required=True, help="Path to project root (use '.' from root).")
    p.add_argument("--output", default="docs/project_structure.md", help="Output markdown file path.")
    return p.parse_args()


def should_exclude(path: Path, project_root: Path) -> bool:
    # exclude any path that has an excluded directory in its relative parts
    rel = path.relative_to(project_root)
    return any(part in DEFAULT_EXCLUDE_DIRS for part in rel.parts)


def main() -> None:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    output_path = (project_root / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect folders and files
    folders = []
    files = []

    for p in project_root.rglob("*"):
        if should_exclude(p, project_root):
            continue
        if p.is_dir():
            folders.append(p)
        elif p.is_file():
            files.append(p)

    # Sort deterministically by relative path
    folders_rel = sorted(str(p.relative_to(project_root)).replace("\\", "/") for p in folders)
    files_rel = sorted(str(p.relative_to(project_root)).replace("\\", "/") for p in files)

    # Write markdown
    lines = []
    lines.append("# Project Structure Snapshot\n")
    lines.append(f"- Generated from: `{project_root}`\n")
    lines.append("## Folders\n")
    lines.append("```text")
    lines.extend(folders_rel)
    lines.append("```\n")
    lines.append("## Files\n")
    lines.append("```text")
    lines.extend(files_rel)
    lines.append("```\n")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ Project structure snapshot written to: {output_path}")


if __name__ == "__main__":
    main()
