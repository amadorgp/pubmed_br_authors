"""
Sandbox script to build articles_unique from articles_all.

Rule:
- One row per PMID
- Keep the most recent extraction based on timestamp in xml_source_file

Output:
- CSV: data/sandbox/articles_unique.csv
- Text log via stdout redirection
"""

import pandas as pd
from pathlib import Path
import re


PROJECT_ROOT = Path(".")
INPUT_CSV = PROJECT_ROOT / "data" / "processed" / "articles_all.csv"
OUTPUT_CSV = PROJECT_ROOT / "data" / "sandbox" / "articles_unique.csv"


TIMESTAMP_PATTERN = re.compile(r"(\d{8}_\d{6})")


def extract_timestamp(xml_name: str):
    if pd.isna(xml_name):
        return pd.NaT
    match = TIMESTAMP_PATTERN.search(xml_name)
    if not match:
        return pd.NaT
    return pd.to_datetime(match.group(1), format="%Y%m%d_%H%M%S")


def main():
    print("Loading articles_all.csv")
    df = pd.read_csv(INPUT_CSV, low_memory=False)

    print(f"Total rows (input): {len(df)}")
    print(f"Distinct PMIDs (input): {df['pmid'].nunique()}")

    print("Extracting extraction timestamp from xml_source_file")
    df["extraction_ts"] = df["xml_source_file"].apply(extract_timestamp) # type: ignore

    missing_ts = df["extraction_ts"].isna().sum()
    print(f"Rows with missing extraction timestamp: {missing_ts}")

    print("Sorting by PMID and extraction timestamp (descending)")
    df_sorted = df.sort_values(
        by=["pmid", "extraction_ts"],
        ascending=[True, False]
    )

    print("Selecting most recent row per PMID")
    articles_unique = df_sorted.drop_duplicates(
        subset=["pmid"],
        keep="first"
    )

    print(f"Total rows (articles_unique): {len(articles_unique)}")
    print(f"Distinct PMIDs (articles_unique): {articles_unique['pmid'].nunique()}")

    print("Saving articles_unique.csv to sandbox")
    articles_unique.drop(columns=["extraction_ts"]).to_csv(
        OUTPUT_CSV,
        index=False
    )

    print("Sandbox build completed successfully.")


if __name__ == "__main__":
    main()
