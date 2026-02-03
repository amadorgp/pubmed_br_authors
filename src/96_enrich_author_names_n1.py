"""
96_enrich_author_names_n1.py

Purpose
-------
Add conservative, non-destructive name normalization columns (N1) to:
- data/processed/author_occurrences_enriched.csv

Adds
----
- author_name_ascii
- author_name_clean
- last_name_norm
- first_name_norm
- initials_norm
- block_key
- name_parse_ok

Notes
-----
- No merges, no entity IDs.
- Conservative parsing for PubMed style: "Last, First Middle ..."
- Keeps original author_name_raw unchanged.
- block_key is for neighborhood only (NOT identity).
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="N1 name normalization for author occurrences (no merges).")
    p.add_argument("--project-root", required=True)
    p.add_argument("--input-csv", default="data/processed/author_occurrences_enriched.csv")
    p.add_argument("--output-csv", default="data/processed/author_occurrences_enriched.csv")
    return p.parse_args()


# ------------------------------------------------------------
# Text utilities (conservative)
# ------------------------------------------------------------
def strip_accents(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(ch)
    )


def normalize_whitespace(s: str) -> str:
    return " ".join(s.split())


def clean_author_text(s: str) -> str:
    """
    Conservative cleaning:
    - lowercase
    - remove accents
    - keep letters/digits/spaces/comma/hyphen
    - normalize hyphen to space
    - collapse whitespace
    """
    s = s.strip().lower()
    s = strip_accents(s)
    s = re.sub(r"[^a-z0-9,\s-]+", " ", s)  # remove punctuation except comma/hyphen
    s = s.replace("-", " ")
    s = normalize_whitespace(s)
    return s


def parse_pubmed_name(author_name_raw: str | None) -> tuple[str | None, str | None, str | None, bool]:
    """
    Expected most common PubMed format:
      "Last, First M Z"

    Returns:
      last_name_norm, first_name_norm, initials_norm, name_parse_ok

    Conservative rules:
    - Requires comma; if absent -> not ok (avoid misleading parsing).
    - last_name_norm: left side of comma
    - first_name_norm: first token on right side
    - initials_norm: first letter of each token on right side (letters only)
    """
    if not isinstance(author_name_raw, str) or not author_name_raw.strip():
        return None, None, None, False

    cleaned = clean_author_text(author_name_raw)

    if "," not in cleaned:
        return None, None, None, False

    left, right = [part.strip() for part in cleaned.split(",", 1)]
    if not left:
        return None, None, None, False

    right_tokens = [t for t in right.split() if t]
    if not right_tokens:
        return normalize_whitespace(left), None, None, False

    last_name_norm = normalize_whitespace(left)
    first_name_norm = right_tokens[0]

    initials = []
    for tok in right_tokens:
        ch = tok[0]
        if "a" <= ch <= "z":
            initials.append(ch)
    initials_norm = "".join(initials) if initials else None

    ok = bool(last_name_norm and first_name_norm and initials_norm)
    return last_name_norm, first_name_norm, initials_norm, ok


def main() -> None:
    args = parse_args()
    root = Path(args.project_root)

    input_path = root / args.input_csv
    output_path = root / args.output_csv

    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    df = pd.read_csv(input_path, low_memory=False)

    # Required column
    if "author_name_raw" not in df.columns:
        raise ValueError("Missing required column: author_name_raw")

    # 1) author_name_ascii: remove accents from raw (keep original punctuation/spaces)
    df["author_name_ascii"] = df["author_name_raw"].apply(
        lambda x: strip_accents(x) if isinstance(x, str) else None
    )

    # 2) author_name_clean: normalized string for grouping (still no merge)
    df["author_name_clean"] = df["author_name_raw"].apply(
        lambda x: clean_author_text(x) if isinstance(x, str) else None
    )

    # 3) Parse into components (conservative)
    parsed = df["author_name_raw"].apply(parse_pubmed_name)
    df["last_name_norm"] = parsed.apply(lambda t: t[0])
    df["first_name_norm"] = parsed.apply(lambda t: t[1])
    df["initials_norm"] = parsed.apply(lambda t: t[2])
    df["name_parse_ok"] = parsed.apply(lambda t: t[3])

    # 4) block_key (VETORIZED, recommended)
    #    block_key = last_name_norm + "_" + initials_norm when both exist
    df["block_key"] = pd.NA
    mask = df["last_name_norm"].notna() & df["initials_norm"].notna()
    df.loc[mask, "block_key"] = (
        df.loc[mask, "last_name_norm"].astype(str)
        + "_"
        + df.loc[mask, "initials_norm"].astype(str)
    )

    # Write output (non-destructive to original columns)
    df.to_csv(output_path, index=False, encoding="utf-8")

    # Minimal run summary
    n_rows = len(df)
    ok_count = int(df["name_parse_ok"].sum())
    print(f"✅ N1 name enrichment written to: {output_path}")
    print(f"rows: {n_rows}")
    print(f"name_parse_ok: {ok_count} ({ok_count / n_rows:.2%})")


if __name__ == "__main__":
    main()
