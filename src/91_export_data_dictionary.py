"""
91_export_data_dictionary.py

Purpose
-------
Export a project-level Data Dictionary from processed datasets.

The Data Dictionary is generated as:
- Markdown (human-readable, documentation)
- CSV (machine-readable, reusable)

This artifact is derived from:
- schema (columns + dtype)
- basic profiling (nulls, nunique)
- column role classification (manual map + heuristics)

Design goals
------------
- Project-wide coverage: auto-discover CSV datasets (including N1/N2/marts)
- Conservative + auditable: deterministic outputs, no hidden assumptions
- Practical ergonomics: progress indicators, skip controls for large datasets if needed

Default discovery:
- data/processed/*.csv

Optional:
- include data/sandbox/*.csv (flag)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd


# -----------------------------------------------------------------------------
# Column roles: explicit overrides (project knowledge)
# -----------------------------------------------------------------------------
COLUMN_ROLES: Dict[str, str] = {
    # identifiers / governance
    "pmid": "primary_identifier",
    "doi": "identifier_optional",
    "orcid": "identifier_optional",
    "xml_source_file": "governance",
    "extraction_date": "governance",
    "strategy_id": "governance",
    "source": "governance",

    # article metadata
    "pub_year": "temporal",
    "journal": "categorical",
    "article_title": "free_text",
    "publication_types": "categorical",
    "abstract": "free_text",

    # author occurrence
    "author_position": "ordinal",
    "author_role": "categorical",
    "author_name_raw": "free_text",
    "affiliation_raw": "free_text",

    # N1 name normalization
    "author_name_ascii": "derived_text",
    "author_name_clean": "derived_text",
    "last_name_norm": "derived_text",
    "first_name_norm": "derived_text",
    "initials_norm": "derived_text",
    "block_key": "derived_identifier",
    "name_parse_ok": "quality_flag",

    # optional enrichments
    "email_extracted": "identifier_optional",
    "affiliation_state_extracted": "categorical",

    # N2 coauthor metrics (diagnostic)
    "n2_n_articles": "metric",
    "n2_n_unique_coauthors": "metric",
    "n2_n_coauthor_edges": "metric",
    "n2_mean_coauthors_per_article": "metric",
    "n2_tier": "categorical",

    # N2 identity resolution (auditável)
    "author_cluster_id": "derived_identifier",
    "author_cluster_size": "metric",

    # marts
    "canonical_author_name": "free_text",
    "block_key_example": "derived_text",
    "email_example": "identifier_optional",
    "state_example": "categorical",
    "n_articles": "metric",
    "n_occurrences": "metric",
    "any_email": "flag",
    "any_br_affiliation": "flag",
    "any_first_author": "flag",
    "source_example": "categorical",
    "n_articles_by_source": "metric",
}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def infer_project_root(project_root_arg: Optional[str]) -> Path:
    if project_root_arg:
        return Path(project_root_arg).resolve()
    # default: repo root is parent of src/
    return Path(__file__).resolve().parents[1]


def role_for_column(col: str) -> str:
    """Return explicit role if known; else infer by conservative heuristics."""
    if col in COLUMN_ROLES:
        return COLUMN_ROLES[col]

    c = col.lower()

    # heuristic identifiers
    if c.endswith("_id") or c.endswith("_key"):
        return "derived_identifier"

    # flags
    if c.startswith("is_") or c.startswith("has_") or c.startswith("any_") or c.endswith("_flag"):
        return "flag"

    # time / dates
    if "date" in c or c.endswith("_ts") or c.endswith("_timestamp") or c.endswith("_year"):
        return "temporal"

    # counts / metrics
    if c.startswith("n_") or c.endswith("_count") or c.endswith("_pct") or c.endswith("_num") or c.endswith("_size"):
        return "metric"

    # free text hints
    if "title" in c or "abstract" in c or "affiliation" in c or "name" in c:
        return "free_text"

    return "unspecified"


def format_pct(x: float) -> str:
    return f"{x:.4f}"


def safe_read_csv(path: Path) -> pd.DataFrame:
    # low_memory=False -> dtypes mais consistentes (vale pro dicionário)
    return pd.read_csv(path, low_memory=False)


def iter_csv_files(
    root: Path,
    include_sandbox: bool,
    exclude_patterns: List[str],
) -> List[Path]:
    paths: List[Path] = []
    processed = root / "data" / "processed"
    if processed.exists():
        paths.extend(sorted(processed.glob("*.csv")))

    if include_sandbox:
        sandbox = root / "data" / "sandbox"
        if sandbox.exists():
            paths.extend(sorted(sandbox.glob("*.csv")))

    # exclusions (substring match)
    out: List[Path] = []
    for p in paths:
        ps = str(p).lower()
        if any(x.lower() in ps for x in exclude_patterns):
            continue
        out.append(p)

    # de-dup
    out = sorted(set(out))
    return out


@dataclass
class DatasetSummary:
    dataset: str
    rel_path: str
    n_rows: int
    n_cols: int


def build_dictionary_for_dataset(df: pd.DataFrame, dataset_name: str, rel_path: str) -> Tuple[pd.DataFrame, DatasetSummary]:
    rows = []
    n_rows = int(len(df))
    n_cols = int(df.shape[1])

    for col in df.columns:
        s = df[col]
        null_count = int(s.isna().sum())
        null_pct = float(null_count / n_rows) if n_rows else 0.0

        rows.append({
            "dataset": dataset_name,
            "rel_path": rel_path,
            "column_name": col,
            "data_type": str(s.dtype),
            "column_role": role_for_column(col),
            "nullable": bool(null_count > 0),
            "nunique": int(s.nunique(dropna=True)),
            "null_count": null_count,
            "null_pct": null_pct,
            "notes": "",
        })

    dd = pd.DataFrame(rows)
    summary = DatasetSummary(
        dataset=dataset_name,
        rel_path=rel_path,
        n_rows=n_rows,
        n_cols=n_cols,
    )
    return dd, summary


def export_markdown(data_dictionary: pd.DataFrame, summaries: List[DatasetSummary], path: Path) -> None:
    def md_escape(val: str) -> str:
        return str(val).replace("|", "\\|")

    def md_table(sub: pd.DataFrame, drop_cols: Optional[List[str]] = None) -> str:
        sub = sub.copy()
        if drop_cols:
            sub = sub.drop(columns=[c for c in drop_cols if c in sub.columns], errors="ignore")

        for c in sub.columns:
            sub[c] = sub[c].astype(str).map(md_escape)

        header = "| " + " | ".join(sub.columns) + " |"
        sep = "| " + " | ".join(["---"] * len(sub.columns)) + " |"
        lines = [header, sep]
        for _, r in sub.iterrows():
            lines.append("| " + " | ".join(r.values.tolist()) + " |")
        return "\n".join(lines)

    # dataset summary table
    summary_df = pd.DataFrame([{
        "dataset": s.dataset,
        "rel_path": s.rel_path,
        "n_rows": s.n_rows,
        "n_cols": s.n_cols,
    } for s in summaries]).sort_values(["dataset"])

    with path.open("w", encoding="utf-8") as f:
        f.write("# Data Dictionary\n\n")
        f.write(f"_Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n\n")

        f.write("## Datasets Summary\n\n")
        f.write(md_table(summary_df))
        f.write("\n\n")

        # per-dataset section
        for dataset, sub in data_dictionary.groupby("dataset", sort=True):
            f.write(f"## Dataset: `{dataset}`\n\n")
            f.write(md_table(
                sub.sort_values(["column_role", "column_name"]),
                drop_cols=[],
            ))
            f.write("\n\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export project-level Data Dictionary (Markdown + CSV).")
    p.add_argument("--project-root", required=False, default=None, help="Project root (optional). If omitted, inferred from script path.")
    p.add_argument("--include-sandbox", action="store_true", help="Also include data/sandbox/*.csv")
    p.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="List of substrings; any CSV path containing a substring will be skipped (case-insensitive).",
    )
    p.add_argument(
        "--output-dir",
        default="docs/data_dictionary",
        help="Relative output directory under project root (default: docs/data_dictionary).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = infer_project_root(args.project_root)

    out_dir = (root / args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_paths = iter_csv_files(
        root=root,
        include_sandbox=bool(args.include_sandbox),
        exclude_patterns=list(args.exclude),
    )

    if not csv_paths:
        raise FileNotFoundError("Nenhum CSV encontrado em data/processed (ou sandbox, se habilitado).")

    print(f"[Data Dictionary] Project root: {root}")
    print(f"[Data Dictionary] Found {len(csv_paths)} CSV file(s).")
    if args.exclude:
        print(f"[Data Dictionary] Exclusions: {args.exclude}")

    all_dd: List[pd.DataFrame] = []
    summaries: List[DatasetSummary] = []

    for i, path in enumerate(csv_paths, start=1):
        rel_path = str(path.relative_to(root)).replace("\\", "/")
        dataset_name = path.stem  # filename without .csv

        print(f"[{i}/{len(csv_paths)}] Reading: {rel_path}")
        df = safe_read_csv(path)

        dd, summary = build_dictionary_for_dataset(df, dataset_name=dataset_name, rel_path=rel_path)
        all_dd.append(dd)
        summaries.append(summary)

        print(f"      -> rows={summary.n_rows} cols={summary.n_cols}")

    data_dictionary = pd.concat(all_dd, ignore_index=True)

    # Normalize null_pct display for CSV (keep numeric) + optional rounding
    # (keep float in CSV; markdown will show full as str anyway)
    data_dictionary["null_pct"] = data_dictionary["null_pct"].astype(float)

    csv_out = out_dir / "data_dictionary.csv"
    md_out = out_dir / "data_dictionary.md"

    data_dictionary.to_csv(csv_out, index=False, encoding="utf-8")
    export_markdown(data_dictionary, summaries, md_out)

    print("\nData Dictionary exported:")
    print(f"- {csv_out}")
    print(f"- {md_out}")


if __name__ == "__main__":
    main()
