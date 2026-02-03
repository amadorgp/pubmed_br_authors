"""
95_profile_author_occurrences_enriched.py

Purpose
-------
Read-only profiling/QA for:
- data/processed/author_occurrences_enriched.csv

Outputs (created if missing)
----------------------------
runs/profiling/author_occurrences_enriched__profile.txt
runs/profiling/samples__emails_present.csv
runs/profiling/samples__states_present.csv
runs/profiling/samples__states_present__no_brazil_keyword.csv

Notes
-----
- Does NOT modify datasets.
- Sampling is reproducible via fixed seed.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Profile author_occurrences_enriched outputs (read-only).")
    p.add_argument("--project-root", required=True)
    p.add_argument("--input-csv", default="data/processed/author_occurrences_enriched.csv")
    p.add_argument("--out-dir", default="runs/profiling")
    p.add_argument("--sample-n", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.project_root)

    input_path = root / args.input_csv
    out_dir = root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    df = pd.read_csv(input_path, low_memory=False)

    required_cols = [
        "pmid",
        "author_name_raw",
        "affiliation_raw",
        "email_extracted",
        "affiliation_state_extracted",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing expected columns in enriched CSV: {missing}")

    n_rows = len(df)

    emails_present = int(df["email_extracted"].notna().sum())
    states_present = int(df["affiliation_state_extracted"].notna().sum())

    affil = df["affiliation_raw"].fillna("").astype(str).str.lower()
    has_brazil_kw = affil.str.contains("brazil") | affil.str.contains("brasil")
    states_present_no_brazil_kw = int((df["affiliation_state_extracted"].notna() & ~has_brazil_kw).sum())

    top_states = (
        df["affiliation_state_extracted"]
        .dropna()
        .value_counts()
        .head(15)
    )

    profile_path = out_dir / "author_occurrences_enriched__profile.txt"
    with profile_path.open("w", encoding="utf-8") as f:
        f.write("PROFILE: author_occurrences_enriched\n")
        f.write(f"rows: {n_rows}\n\n")
        f.write("COLUMN COMPLETENESS\n")
        f.write(f"email_extracted not-null: {emails_present} ({emails_present / n_rows:.2%})\n")
        f.write(f"affiliation_state_extracted not-null: {states_present} ({states_present / n_rows:.2%})\n")
        f.write("\nBRAZIL KEYWORD CHECK (state extracted but no 'brazil/brasil' keyword)\n")
        f.write(f"count: {states_present_no_brazil_kw} ({states_present_no_brazil_kw / n_rows:.2%})\n")
        f.write("\nTOP 15 STATES (by extracted count)\n")
        for uf, cnt in top_states.items():
            f.write(f"{uf}: {cnt}\n")

    sample_cols = ["pmid", "author_name_raw", "affiliation_raw", "email_extracted", "affiliation_state_extracted"]

    df_emails = df[df["email_extracted"].notna()][sample_cols]
    (df_emails.sample(n=min(args.sample_n, len(df_emails)), random_state=args.seed)
     if len(df_emails) > 0 else df_emails).to_csv(
        out_dir / "samples__emails_present.csv", index=False, encoding="utf-8"
    )

    df_states = df[df["affiliation_state_extracted"].notna()][sample_cols]
    (df_states.sample(n=min(args.sample_n, len(df_states)), random_state=args.seed)
     if len(df_states) > 0 else df_states).to_csv(
        out_dir / "samples__states_present.csv", index=False, encoding="utf-8"
    )

    df_states_no_br = df[df["affiliation_state_extracted"].notna() & ~has_brazil_kw][sample_cols]
    (df_states_no_br.sample(n=min(args.sample_n, len(df_states_no_br)), random_state=args.seed)
     if len(df_states_no_br) > 0 else df_states_no_br).to_csv(
        out_dir / "samples__states_present__no_brazil_keyword.csv", index=False, encoding="utf-8"
    )

    print("✅ Profiling outputs written to:")
    print(f" - {profile_path}")
    print(f" - {out_dir / 'samples__emails_present.csv'}")
    print(f" - {out_dir / 'samples__states_present.csv'}")
    print(f" - {out_dir / 'samples__states_present__no_brazil_keyword.csv'}")


if __name__ == "__main__":
    main()
