"""
102_export_leads_p1_with_email.py

Purpose
-------
Export the final lead list for outreach:
- Only P1_BR_Clinical
- Only authors with at least one extracted email (any_email == True)
- No extra heuristics to validate "email ownership" (treated as contact channel)

Input
-----
data/processed/mart_leads_authors_v2.csv

Output
------
data/processed/leads_p1_with_email.csv
runs/logs/<run_id>_export_leads_p1_with_email.log
runs/manifests/<run_id>_export_leads_p1_with_email.json

Notes
-----
- Keeps n_articles as an informative field (no filtering).
- Adds a light bucket (n_articles_tier) to help outreach prioritization without changing eligibility.
- Maintains auditability: counts + parameters in manifest.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


# -----------------------------
# Utilities: run id, dirs, logs
# -----------------------------
def make_run_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = hex(abs(hash(stamp)))[-8:]
    return f"{stamp}_{rand}"


def ensure_dirs(project_root: Path) -> Dict[str, Path]:
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
    logger = logging.getLogger("export_leads_p1_with_email")
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


# -----------------------------
# Business rules (frozen V1)
# -----------------------------
P1_LABEL = "P1_BR_Clinical"


def n_articles_tier(n: Any) -> str:
    """Small, non-destructive bucket for outreach prioritization."""
    try:
        if pd.isna(n):
            return "unknown"
        x = int(n)
    except Exception:
        return "unknown"

    if x <= 1:
        return "1"
    if 2 <= x <= 3:
        return "2-3"
    if 4 <= x <= 7:
        return "4-7"
    return "8+"


# -----------------------------
# Manifest schema
# -----------------------------
@dataclass
class ExportMetrics:
    input_rows: int
    input_cols: int
    input_path: str

    p1_rows: int
    p1_with_email_rows: int
    output_rows: int
    output_cols: int
    output_path: str

    distinct_authors_output: int
    any_email_rate_within_p1: float

    selected_columns: List[str]
    notes: str | None = None


def main() -> int:
    run_id = make_run_id()
    dirs = ensure_dirs(PROJECT_ROOT)
    log_path = dirs["logs"] / f"{run_id}_export_leads_p1_with_email.log"
    logger = configure_logger(log_path)

    started_utc = datetime.now(timezone.utc).isoformat()

    input_csv = PROJECT_ROOT / "data" / "processed" / "mart_leads_authors_v2.csv"
    output_csv = PROJECT_ROOT / "data" / "processed" / "leads_p1_with_email.csv"
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    manifest_path = dirs["manifests"] / f"{run_id}_export_leads_p1_with_email.json"

    logger.info("OK: 102_export_leads_p1_with_email")
    logger.info("ProjectRoot: %s", PROJECT_ROOT)
    logger.info("Input: %s", input_csv)

    if not input_csv.exists():
        raise FileNotFoundError(f"Missing input file: {input_csv}")

    df = pd.read_csv(input_csv, low_memory=False)
    input_rows = int(len(df))
    input_cols = int(df.shape[1])

    required = {"author_cluster_id", "lead_priority", "any_email"}
    missing = sorted(list(required - set(df.columns)))
    if missing:
        raise ValueError(f"Missing required columns in mart_leads_authors_v2.csv: {missing}")

    # Normalize types safely
    df["lead_priority"] = df["lead_priority"].astype(str)
    df["any_email"] = df["any_email"].fillna(False).astype(bool)

    # Filter: P1 only
    df_p1 = df[df["lead_priority"] == P1_LABEL].copy()
    p1_rows = int(len(df_p1))

    # Filter: P1 + email
    df_out = df_p1[df_p1["any_email"]].copy()
    p1_with_email_rows = int(len(df_out))

    # Defensive: keep only rows with author_cluster_id present (avoid empty IDs)
    if "author_cluster_id" in df_out.columns:
        df_out = df_out[df_out["author_cluster_id"].notna()].copy()

    # Add helpful, non-destructive fields
    if "n_articles" in df_out.columns:
        df_out["n_articles_tier"] = df_out["n_articles"].apply(n_articles_tier)
    else:
        df_out["n_articles_tier"] = "unknown"

    # Select a stable set of columns if present (don’t break if some are missing)
    preferred_cols = [
        "author_cluster_id",
        "canonical_author_name",
        "email_example",
        "state_example",
        "n_articles",
        "n_articles_tier",
        "n_occurrences",
        "author_cluster_size",
        "block_key_example",
        "source_example",
        "any_br_affiliation",
        "any_clinical",
        "lead_priority",
    ]

    selected_cols = [c for c in preferred_cols if c in df_out.columns]

    # Fallback: if key display columns are missing, keep all columns (never fail silently)
    if "author_cluster_id" not in selected_cols:
        selected_cols = list(df_out.columns)

    df_out = df_out[selected_cols].copy()

    # Sort for outreach: low publishers first (tier then n_articles)
    sort_cols = [c for c in ["n_articles_tier", "n_articles", "canonical_author_name"] if c in df_out.columns]
    if sort_cols:
        df_out = df_out.sort_values(sort_cols, ascending=True, na_position="last")

    df_out.to_csv(output_csv, index=False, encoding="utf-8")

    output_rows = int(len(df_out))
    output_cols = int(df_out.shape[1])

    distinct_authors_output = int(df_out["author_cluster_id"].nunique(dropna=True)) if "author_cluster_id" in df_out.columns else 0
    rate = float(p1_with_email_rows / p1_rows) if p1_rows else 0.0

    metrics = ExportMetrics(
        input_rows=input_rows,
        input_cols=input_cols,
        input_path=str(input_csv),

        p1_rows=p1_rows,
        p1_with_email_rows=p1_with_email_rows,
        output_rows=output_rows,
        output_cols=output_cols,
        output_path=str(output_csv),

        distinct_authors_output=distinct_authors_output,
        any_email_rate_within_p1=rate,

        selected_columns=selected_cols,
        notes="Emails treated as contact channels associated with an authorship cluster; no ownership validation heuristics applied.",
    )

    manifest = {
        "run_id": run_id,
        "stage": "export_leads_p1_with_email",
        "created_at_utc": started_utc,
        "project_root": str(PROJECT_ROOT),
        "params": {
            "p1_label": P1_LABEL,
            "filters": [
                "lead_priority == P1_BR_Clinical",
                "any_email == True",
                "author_cluster_id not null",
            ],
            "input_csv": str(input_csv),
            "output_csv": str(output_csv),
        },
        "metrics": asdict(metrics),
    }

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("Output: %s | shape=(%d, %d)", output_csv, output_rows, output_cols)
    logger.info("P1 rows: %d | P1 with email: %d | rate: %.4f", p1_rows, p1_with_email_rows, rate)
    logger.info("Distinct authors in output: %d", distinct_authors_output)
    logger.info("Log: %s", log_path)
    logger.info("Manifest: %s", manifest_path)

    print(f"OK: 102_export_leads_p1_with_email")
    print(f"Input:  {input_csv} | shape=({input_rows}, {input_cols})")
    print(f"Output: {output_csv} | shape=({output_rows}, {output_cols})")
    print(f"P1 rows: {p1_rows} | P1 with email: {p1_with_email_rows} | rate: {rate:.4f}")
    print(f"Distinct authors in output: {distinct_authors_output}")
    print(f"Log: {log_path}")
    print(f"Manifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(2)
