"""
93_build_author_occurrences_unique.py

Build a semantically unique author occurrences table from author_occurrences_all.csv.

Context
-------
author_occurrences_all.csv may contain technical duplicates because the same PMID
can appear in more than one extraction batch (different xml_source_file). In this
project, duplicates were confirmed (via sandbox) to be identical across all columns
except xml_source_file for the same (pmid, author_position).

Therefore, we preserve the full extraction history in author_occurrences_all and
create a derived dataset author_occurrences_unique with one row per (pmid, author_position).

Selection rule (official)
-------------------------
For each (pmid, author_position):
- Parse extraction timestamp from xml_source_file (pattern: YYYYMMDD_HHMMSS)
- Keep the row with the most recent timestamp
- Stable tie-breaker: xml_source_file descending

Inputs
------
data/processed/author_occurrences_all.csv

Outputs
-------
data/processed/author_occurrences_unique.csv
runs/logs/<run_id>_build_author_occurrences_unique.log
runs/manifests/<run_id>_build_author_occurrences_unique.json
runs/checkpoints/<run_id>_rows_missing_timestamp_sample.csv (only if needed)

Exit codes
----------
0: success
2: error (exception)
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


TIMESTAMP_PATTERN = re.compile(r"(\d{8}_\d{6})")


@dataclass
class BuildMetrics:
    input_rows: int
    input_distinct_pmids: int
    input_distinct_key: int
    duplicated_keys: int
    missing_timestamp_rows: int
    output_rows: int
    output_distinct_pmids: int
    output_distinct_key: int
    notes: str | None = None


def parse_args(argv: list[str]) -> dict[str, Any]:
    project_root = "."
    if "--project-root" in argv:
        i = argv.index("--project-root")
        if i + 1 >= len(argv):
            raise ValueError("Missing value for --project-root")
        project_root = argv[i + 1]
    return {"project_root": Path(project_root)}


def make_run_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = hex(abs(hash(stamp)))[-8:]
    return f"{stamp}_{rand}"


def ensure_dirs(project_root: Path) -> dict[str, Path]:
    runs = project_root / "runs"
    dirs = {
        "logs": runs / "logs",
        "manifests": runs / "manifests",
        "checkpoints": runs / "checkpoints",
    }
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    return dirs


def configure_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("build_author_occurrences_unique")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


def extract_ts(xml_name: Any) -> pd.Timestamp:
    if pd.isna(xml_name):
        return pd.NaT # type: ignore
    m = TIMESTAMP_PATTERN.search(str(xml_name))
    if not m:
        return pd.NaT # type: ignore
    return pd.to_datetime(m.group(1), format="%Y%m%d_%H%M%S", errors="coerce") # type: ignore


def main() -> int:
    args = parse_args(sys.argv[1:])
    project_root: Path = args["project_root"].resolve()

    run_id = make_run_id()
    dirs = ensure_dirs(project_root)
    log_path = dirs["logs"] / f"{run_id}_build_author_occurrences_unique.log"
    logger = configure_logger(log_path)

    started_utc = datetime.now(timezone.utc).isoformat()

    input_csv = project_root / "data" / "processed" / "author_occurrences_all.csv"
    output_csv = project_root / "data" / "processed" / "author_occurrences_unique.csv"
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    manifest_path = dirs["manifests"] / f"{run_id}_build_author_occurrences_unique.json"

    logger.info("Reading input CSV: %s", input_csv)
    df = pd.read_csv(input_csv, low_memory=False)

    required = {"pmid", "author_position", "xml_source_file"}
    missing_cols = sorted(list(required - set(df.columns)))
    if missing_cols:
        raise ValueError(f"Missing required columns in author_occurrences_all.csv: {missing_cols}")

    key_cols = ["pmid", "author_position"]

    input_rows = int(len(df))
    input_distinct_pmids = int(df["pmid"].nunique(dropna=True))
    input_distinct_key = int(df[key_cols].drop_duplicates().shape[0])

    key_counts = df.groupby(key_cols, dropna=False).size()
    duplicated_keys = int((key_counts > 1).sum())

    logger.info(
        "Input rows: %d | distinct PMIDs: %d | distinct (pmid,author_position): %d | duplicated keys: %d",
        input_rows,
        input_distinct_pmids,
        input_distinct_key,
        duplicated_keys,
    )

    logger.info("Extracting timestamp from xml_source_file...")
    df["extraction_ts"] = df["xml_source_file"].apply(extract_ts)
    missing_timestamp_rows = int(df["extraction_ts"].isna().sum())
    logger.info("Rows with missing extracted timestamp: %d", missing_timestamp_rows)

    logger.info("Sorting and selecting most recent row per (pmid, author_position)...")
    df_sorted = df.sort_values(
        by=["pmid", "author_position", "extraction_ts", "xml_source_file"],
        ascending=[True, True, False, False],
    )

    unique_occ = df_sorted.drop_duplicates(subset=key_cols, keep="first").copy()

    output_rows = int(len(unique_occ))
    output_distinct_pmids = int(unique_occ["pmid"].nunique(dropna=True))
    output_distinct_key = int(unique_occ[key_cols].drop_duplicates().shape[0])

    logger.info(
        "Output rows (author_occurrences_unique): %d | distinct PMIDs: %d | distinct key: %d",
        output_rows,
        output_distinct_pmids,
        output_distinct_key,
    )

    notes = None
    checkpoint_path = None
    if missing_timestamp_rows > 0:
        notes = "Some rows had missing extraction timestamp parsed from xml_source_file."
        checkpoint_path = dirs["checkpoints"] / f"{run_id}_rows_missing_timestamp_sample.csv"
        df[df["extraction_ts"].isna()].head(500).to_csv(checkpoint_path, index=False)
        logger.info("Checkpoint saved (missing timestamp sample): %s", checkpoint_path)

    logger.info("Writing output CSV: %s", output_csv)
    unique_occ.drop(columns=["extraction_ts"]).to_csv(output_csv, index=False)

    finished_utc = datetime.now(timezone.utc).isoformat()

    metrics = BuildMetrics(
        input_rows=input_rows,
        input_distinct_pmids=input_distinct_pmids,
        input_distinct_key=input_distinct_key,
        duplicated_keys=duplicated_keys,
        missing_timestamp_rows=missing_timestamp_rows,
        output_rows=output_rows,
        output_distinct_pmids=output_distinct_pmids,
        output_distinct_key=output_distinct_key,
        notes=notes,
    )

    manifest = {
        "run_id": run_id,
        "script": "93_build_author_occurrences_unique.py",
        "started_at_utc": started_utc,
        "finished_at_utc": finished_utc,
        "inputs": {
            "author_occurrences_all_csv": str(input_csv),
        },
        "outputs": {
            "author_occurrences_unique_csv": str(output_csv),
            "log": str(log_path),
            "checkpoint_sample_missing_timestamp": str(checkpoint_path) if checkpoint_path else None,
        },
        "metrics": asdict(metrics),
        "status": "OK",
    }

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Build completed. Manifest: %s", manifest_path)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
