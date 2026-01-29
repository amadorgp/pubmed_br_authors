"""
Sandbox script to investigate PMID duplication in articles_all.csv.

Purpose:
- Identify duplicated PMIDs
- Inspect whether duplicated rows are identical or differ
- Help define deduplication or key strategy

This script is intentionally simple:
- No logs
- No manifests
- Uses print for inspection
"""

import pandas as pd
from pathlib import Path


# ---- Paths (adjust only if needed) ----
PROJECT_ROOT = Path(".")
ARTICLES_CSV = PROJECT_ROOT / "data" / "processed" / "articles_all.csv"


def main() -> None:
    print("Loading articles_all.csv...")
    df = pd.read_csv(ARTICLES_CSV, low_memory=False)

    print(f"Total rows: {len(df)}")
    print(f"Distinct PMIDs: {df['pmid'].nunique()}")

    # Find duplicated PMIDs
    duplicated_pmids = (
        df["pmid"]
        .value_counts()
        .loc[lambda s: s > 1]
    )

    print("\nPMIDs with more than one occurrence:")
    print(duplicated_pmids.head(10))
    print(f"\nTotal duplicated PMIDs: {len(duplicated_pmids)}")

    # Pick one duplicated PMID to inspect
    sample_pmid = duplicated_pmids.index[0]
    print(f"\nInspecting duplicated PMID: {sample_pmid}")

    subset = df[df["pmid"] == sample_pmid]
    print("\nRows for this PMID:")
    print(subset)

    print("\nAre duplicated rows fully identical?")
    print(subset.duplicated().all())

    print("\nColumn-wise comparison:")
    for col in df.columns:
        unique_vals = subset[col].nunique(dropna=False)
        if unique_vals > 1:
            print(f" - Column differs: {col}")
            print(subset[col].unique())

    print("\nSandbox exploration completed.")


if __name__ == "__main__":
    main()
