"""
91_export_data_dictionary.py

Purpose
-------
Export a project-level Data Dictionary from processed datasets.

The Data Dictionary is generated as:
- Markdown (human-readable, documentation)
- CSV (machine-readable, reusable)

This artifact is derived from:
- schema
- profiling results
- column role classification

It is intended to be versioned alongside the project documentation.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd


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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export Data Dictionary (Markdown + CSV).")
    p.add_argument("--project-root", required=True)
    p.add_argument("--articles-csv", default="data/processed/articles_all.csv")
    p.add_argument("--authors-csv", default="data/processed/author_occurrences_all.csv")
    p.add_argument("--articles-unique-csv", default="data/processed/articles_unique.csv")
    p.add_argument("--authors-unique-csv", default="data/processed/author_occurrences_unique.csv")
    return p.parse_args()


def build_dictionary(df: pd.DataFrame, dataset_name: str) -> pd.DataFrame:
    rows = []
    n_rows = len(df)

    for col in df.columns:
        series = df[col]
        rows.append({
            "dataset": dataset_name,
            "column_name": col,
            "data_type": str(series.dtype),
            "column_role": COLUMN_ROLES.get(col, "unspecified"),
            "nullable": bool(series.isna().any()),
            "nunique": int(series.nunique(dropna=True)),
            "null_count": int(series.isna().sum()),
            "null_pct": float(series.isna().sum() / n_rows if n_rows else 0.0),
            "notes": "",
        })

    return pd.DataFrame(rows)


def export_markdown(df: pd.DataFrame, path: Path) -> None:
    def md_table(sub: pd.DataFrame) -> str:
        sub = sub.drop(columns=["dataset"]).copy()
        # escape pipes to avoid breaking markdown tables
        for col in sub.columns:
            sub[col] = sub[col].astype(str).str.replace("|", "\\|", regex=False)

        header = "| " + " | ".join(sub.columns) + " |"
        sep = "| " + " | ".join(["---"] * len(sub.columns)) + " |"
        lines = [header, sep]
        for _, row in sub.iterrows():
            lines.append("| " + " | ".join(row.values.tolist()) + " |")
        return "\n".join(lines)

    with path.open("w", encoding="utf-8") as f:
        f.write("# Data Dictionary\n\n")
        for dataset, sub in df.groupby("dataset"):
            f.write(f"## Dataset: `{dataset}`\n\n")
            f.write(md_table(sub))
            f.write("\n\n")


def main() -> None:
    args = parse_args()
    root = Path(args.project_root)

    docs_dir = root / "docs" / "data_dictionary"
    docs_dir.mkdir(parents=True, exist_ok=True)

    articles = pd.read_csv(root / args.articles_csv, low_memory=False)
    authors = pd.read_csv(root / args.authors_csv, low_memory=False)
    articles_unique = pd.read_csv(root / args.articles_unique_csv, low_memory=False)
    authors_unique = pd.read_csv(root / args.authors_unique_csv, low_memory=False)

    dd_articles = build_dictionary(articles, "articles_all")
    dd_authors = build_dictionary(authors, "author_occurrences_all")
    dd_articles_unique = build_dictionary(articles_unique, "articles_unique")
    dd_authors_unique = build_dictionary(authors_unique, "author_occurrences_unique")

    data_dictionary = pd.concat(
        [
            dd_articles,
            dd_articles_unique,
            dd_authors,
            dd_authors_unique,
        ],
        ignore_index=True
    )


    csv_path = docs_dir / "data_dictionary.csv"
    md_path = docs_dir / "data_dictionary.md"

    data_dictionary.to_csv(csv_path, index=False, encoding="utf-8")
    export_markdown(data_dictionary, md_path)

    print(f"Data Dictionary exported:\n- {csv_path}\n- {md_path}")


if __name__ == "__main__":
    main()
