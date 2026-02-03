"""
97_profile_author_names_n1.py

Purpose
-------
Read-only QA for N1 name normalization columns added to:
- data/processed/author_occurrences_enriched.csv

Outputs
-------
runs/profiling/names_n1__profile.txt
runs/profiling/names_n1__samples__parse_ok.csv
runs/profiling/names_n1__samples__parse_fail.csv
runs/profiling/names_n1__top_block_keys.csv

Notes
-----
- Does NOT modify data.
- Sampling is reproducible (seed).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="QA for N1 name normalization columns (read-only).")
    p.add_argument("--project-root", required=True)
    p.add_argument("--input-csv", default="data/processed/author_occurrences_enriched.csv")
    p.add_argument("--out-dir", default="runs/profiling")
    p.add_argument("--sample-n", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--top-n", type=int, default=30)
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
        "author_name_clean",
        "last_name_norm",
        "first_name_norm",
        "initials_norm",
        "block_key",
        "name_parse_ok",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing expected columns: {missing}")

    n_rows = len(df)
    ok_count = int(df["name_parse_ok"].fillna(False).sum())
    fail_count = n_rows - ok_count

    block_key_nonnull = int(df["block_key"].notna().sum())
    distinct_block_keys = int(df["block_key"].nunique(dropna=True))

    # Top block_keys (useful to detect very common names)
    top_block_keys = (
        df["block_key"]
        .dropna()
        .value_counts()
        .head(args.top_n)
        .reset_index()
    )
    top_block_keys.columns = ["block_key", "rows"]

    # Write profile TXT
    profile_path = out_dir / "names_n1__profile.txt"
    with profile_path.open("w", encoding="utf-8") as f:
        f.write("PROFILE: names N1 (author_occurrences_enriched)\n")
        f.write(f"rows: {n_rows}\n\n")
        f.write("PARSE QUALITY\n")
        f.write(f"name_parse_ok: {ok_count} ({ok_count / n_rows:.2%})\n")
        f.write(f"name_parse_fail: {fail_count} ({fail_count / n_rows:.2%})\n\n")
        f.write("BLOCK KEY COVERAGE\n")
        f.write(f"block_key not-null: {block_key_nonnull} ({block_key_nonnull / n_rows:.2%})\n")
        f.write(f"distinct block_keys: {distinct_block_keys}\n\n")
        f.write(f"TOP {args.top_n} BLOCK_KEYS (rows)\n")
        for _, row in top_block_keys.iterrows():
            f.write(f"{row['block_key']}: {int(row['rows'])}\n")

    # Export top block_keys table
    top_block_keys.to_csv(out_dir / "names_n1__top_block_keys.csv", index=False, encoding="utf-8")

    # Samples for inspection (ok)
    sample_cols = [
        "pmid",
        "author_name_raw",
        "author_name_clean",
        "last_name_norm",
        "first_name_norm",
        "initials_norm",
        "block_key",
    ]

    df_ok = df[df["name_parse_ok"] == True][sample_cols]
    df_fail = df[df["name_parse_ok"] != True][sample_cols]

    df_ok.sample(n=min(args.sample_n, len(df_ok)), random_state=args.seed).to_csv(
        out_dir / "names_n1__samples__parse_ok.csv", index=False, encoding="utf-8"
    )

    if len(df_fail) > 0:
        df_fail.sample(n=min(args.sample_n, len(df_fail)), random_state=args.seed).to_csv(
            out_dir / "names_n1__samples__parse_fail.csv", index=False, encoding="utf-8"
        )
    else:
        (out_dir / "names_n1__samples__parse_fail.csv").write_text("", encoding="utf-8")

    print("✅ N1 name QA outputs written to:")
    print(f" - {profile_path}")
    print(f" - {out_dir / 'names_n1__top_block_keys.csv'}")
    print(f" - {out_dir / 'names_n1__samples__parse_ok.csv'}")
    print(f" - {out_dir / 'names_n1__samples__parse_fail.csv'}")


if __name__ == "__main__":
    main()
