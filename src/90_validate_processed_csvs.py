"""
90_validate_processed_csvs.py

Purpose
-------
Execute a deterministic, full-scan data quality validation on processed PubMed datasets.

This script represents an initial Data Quality Assessment stage, aligned with
widely accepted data management practices (e.g., ISO/IEC 25012 dimensions and
DAMA-DMBOK principles), without claiming full regulatory compliance.

Scope
-----
Datasets:
- articles_all.csv
- author_occurrences_all.csv

Validations performed:
- Schema presence and basic typing assumptions
- Primary key uniqueness (PMID) for articles
- Referential integrity (authors -> articles via PMID)
- Completeness (null counts and percentages)
- Cardinality (nunique per column)
- Numeric sanity checks (min/max)
- Lightweight format proxies (DOI, ORCID)
- Column role classification (data dictionary seed)

Artifacts:
- Logs: runs/logs/
- Manifest (JSON): runs/manifests/
- Evidence (CSV): runs/checkpoints/

Style & Documentation
---------------------
- PEP 8 compliant
- PEP 257 module and function docstrings
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------
# Data Dictionary (initial, extensible)
# ---------------------------------------------------------------------

COLUMN_ROLES = {
    "pmid": "primary_identifier",
    "pub_year": "temporal",
    "journal": "categorical",
    "article_title": "free_text",
    "doi": "identifier_optional",
    "publication_types": "categorical",
    "abstract": "free_text",
    "xml_source_file": "governance",
    "extraction_date": "governance",
    "strategy_id": "governance",
    "source": "governance",
    "author_position": "ordinal",
    "author_role": "categorical",
    "author_name_raw": "free_text",
    "orcid": "identifier_optional",
    "affiliation_raw": "free_text",
}


# ---------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class DatasetProfile:
    dataset: str
    path: str
    n_rows: int
    n_cols: int
    null_counts: dict[str, int]
    null_pct: dict[str, float]
    nunique: dict[str, int]
    numeric_minmax: dict[str, dict[str, float | None]]
    column_roles: dict[str, str]
    notes: list[str]


# ---------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------

def utc_now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def make_run_id() -> str:
    """Create a sortable run identifier."""
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def ensure_dirs(project_root: Path) -> dict[str, Path]:
    """Ensure runs subdirectories exist."""
    runs_dir = project_root / "runs"
    paths = {
        "logs": runs_dir / "logs",
        "manifests": runs_dir / "manifests",
        "checkpoints": runs_dir / "checkpoints",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def setup_logger(log_path: Path) -> logging.Logger:
    """Configure file + stdout logger."""
    logger = logging.getLogger("validate_processed_csvs")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(formatter)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def read_csv(path: Path, logger: logging.Logger) -> pd.DataFrame:
    """Read CSV file with conservative pandas settings."""
    logger.info("Reading CSV: %s", path)
    return pd.read_csv(path, low_memory=False)


# ---------------------------------------------------------------------
# Profiling and checks
# ---------------------------------------------------------------------

def profile_dataframe(
    df: pd.DataFrame,
    dataset: str,
    path: Path,
    numeric_cols: list[str],
) -> DatasetProfile:
    """Compute full-scan profiling metrics for a dataframe."""
    n_rows, n_cols = df.shape

    null_counts = df.isna().sum().astype(int).to_dict()
    null_pct = {k: (v / n_rows if n_rows else 0.0) for k, v in null_counts.items()}
    nunique = df.nunique(dropna=True).astype(int).to_dict()

    numeric_minmax: dict[str, dict[str, float | None]] = {}
    for col in numeric_cols:
        if col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce")
            numeric_minmax[col] = {
                "min": None if s.dropna().empty else float(s.min()),
                "max": None if s.dropna().empty else float(s.max()),
            }

    roles = {c: COLUMN_ROLES.get(c, "unspecified") for c in df.columns}

    return DatasetProfile(
        dataset=dataset,
        path=str(path),
        n_rows=int(n_rows),
        n_cols=int(n_cols),
        null_counts=null_counts,
        null_pct={k: float(v) for k, v in null_pct.items()},
        nunique=nunique,
        numeric_minmax=numeric_minmax,
        column_roles=roles,
        notes=[],
    )


def check_articles_pmid_uniqueness(
    articles: pd.DataFrame,
    checkpoints_dir: Path,
    run_id: str,
    logger: logging.Logger,
) -> dict[str, Any]:
    """
    Check that articles_all has exactly one row per PMID.

    A duplicate PMID is defined as any PMID with frequency > 1.
    """
    pmid = pd.to_numeric(articles.get("pmid"), errors="coerce") # type: ignore

    # Count frequency per PMID (excluding nulls)
    pmid_counts = (
        pmid.dropna()
        .value_counts()
    )

    # PMIDs that appear more than once
    duplicated_pmids = pmid_counts[pmid_counts > 1]

    n_duplicated_pmids = int(duplicated_pmids.shape[0])
    n_duplicated_rows = int(duplicated_pmids.sum())

    evidence_path = None
    if n_duplicated_pmids > 0:
        evidence_path = checkpoints_dir / f"{run_id}_articles_pmid_duplicates.csv"
        (
            duplicated_pmids
            .rename_axis("pmid")
            .reset_index(name="count")
            .sort_values("pmid")
            .to_csv(evidence_path, index=False)
        )


    logger.info(
        "PMID uniqueness check: duplicated_pmids=%d | duplicated_rows=%d",
        n_duplicated_pmids,
        n_duplicated_rows,
    )

    return {
        "duplicate_pmids": n_duplicated_pmids,
        "duplicate_rows": n_duplicated_rows,
        "evidence_csv": str(evidence_path) if evidence_path else None,
    }



def check_referential_integrity(
    articles: pd.DataFrame,
    authors: pd.DataFrame,
) -> dict[str, int]:
    """Check that all author PMIDs exist in articles."""
    art_pmids = set(pd.to_numeric(articles["pmid"], errors="coerce").dropna())
    auth_pmids = set(pd.to_numeric(authors["pmid"], errors="coerce").dropna())

    orphan_pmids = auth_pmids - art_pmids

    return {
        "orphan_pmids": len(orphan_pmids),
    }


def optional_pattern_checks(
    articles: pd.DataFrame,
    authors: pd.DataFrame,
) -> list[str]:
    """Lightweight format proxy checks."""
    notes: list[str] = []

    if "doi" in articles.columns:
        doi = articles["doi"].astype("string").dropna().str.strip()
        bad = doi[~doi.str.startswith("10.", na=False)]
        notes.append(f"DOI nonnull={len(doi)}, not_starting_10dot={len(bad)}")

    if "orcid" in authors.columns:
        orcid = authors["orcid"].astype("string").dropna().str.strip()
        pat = re.compile(r"^\\d{4}-\\d{4}-\\d{4}-\\d{3}[\\dX]$")
        bad = orcid[~orcid.str.match(pat, na=False)]
        notes.append(f"ORCID nonnull={len(orcid)}, bad_format_proxy={len(bad)}")

    return notes


# ---------------------------------------------------------------------
# CLI and main
# ---------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Validate processed PubMed CSVs (full scan).")
    p.add_argument("--project-root", required=True, help="Path to project root.")
    p.add_argument("--articles-csv", default="data/processed/articles_all.csv")
    p.add_argument("--authors-csv", default="data/processed/author_occurrences_all.csv")
    return p.parse_args()


def main() -> int:
    """Main execution entrypoint."""
    args = parse_args()
    project_root = Path(args.project_root)

    run_id = make_run_id()
    dirs = ensure_dirs(project_root)

    log_path = dirs["logs"] / f"{run_id}_validate_processed_csvs.log"
    manifest_path = dirs["manifests"] / f"{run_id}_validate_processed_csvs.json"
    logger = setup_logger(log_path)

    articles_path = project_root / args.articles_csv
    authors_path = project_root / args.authors_csv

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "stage": "validate_processed_csvs",
        "started_at_utc": utc_now_iso(),
        "inputs": {
            "articles_csv": str(articles_path),
            "authors_csv": str(authors_path),
        },
        "results": {},
        "status": "STARTED",
    }

    articles = read_csv(articles_path, logger)
    authors = read_csv(authors_path, logger)

    art_profile = profile_dataframe(
        articles,
        "articles_all",
        articles_path,
        numeric_cols=["pmid", "pub_year"],
    )
    auth_profile = profile_dataframe(
        authors,
        "author_occurrences_all",
        authors_path,
        numeric_cols=["pmid", "pub_year", "author_position"],
    )

    pmid_check = check_articles_pmid_uniqueness(articles, dirs["checkpoints"], run_id, logger)
    ref_check = check_referential_integrity(articles, authors)

    notes = optional_pattern_checks(articles, authors)
    art_profile.notes.extend(notes)
    auth_profile.notes.extend(notes)

    manifest["results"] = {
        "articles_profile": asdict(art_profile),
        "authors_profile": asdict(auth_profile),
        "pmid_uniqueness": pmid_check,
        "referential_integrity": ref_check,
    }
    manifest["status"] = "OK"
    manifest["finished_at_utc"] = utc_now_iso()

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Validation completed. Manifest: %s", manifest_path)

    if pmid_check["duplicate_pmids"] > 0 or ref_check["orphan_pmids"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
