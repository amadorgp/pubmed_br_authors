from __future__ import annotations

import sys
import platform
from datetime import datetime
from pathlib import Path
import json

import requests
import pandas as pd
from lxml import etree  # noqa: F401
from tqdm import tqdm  # noqa: F401


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def ensure_directories():
    paths = [
        PROJECT_ROOT / "config",
        PROJECT_ROOT / "src",
        PROJECT_ROOT / "data" / "raw" / "esearch",
        PROJECT_ROOT / "data" / "raw" / "efetch_xml",
        PROJECT_ROOT / "data" / "processed" / "author_occurrences",
        PROJECT_ROOT / "data" / "processed" / "aggregates",
        PROJECT_ROOT / "runs" / "logs",
        PROJECT_ROOT / "runs" / "checkpoints",
        PROJECT_ROOT / "runs" / "manifests",
    ]
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)
    return paths


def write_manifest():
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_ENV_CHECK"
    manifest_path = PROJECT_ROOT / "runs" / "manifests" / f"{run_id}.json"

    manifest = {
        "run_id": run_id,
        "stage": "environment_validation",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "system": {
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "executable": sys.executable,
        },
        "libraries": {
            "requests": requests.__version__,
            "pandas": pd.__version__,
        },
        "notes": "Environment validation only. No PubMed queries executed.",
    }

    manifest_path.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8"
    )
    return manifest_path


def main():
    print("== ENVIRONMENT VALIDATION ==")
    print("Python version:", sys.version)
    print("Python executable:", sys.executable)
    print("Project root:", PROJECT_ROOT)

    ensure_directories()
    manifest_path = write_manifest()

    print("Directories OK")
    print("Manifest created:", manifest_path)
    print("STATUS: OK")


if __name__ == "__main__":
    main()
