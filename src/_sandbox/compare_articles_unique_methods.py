"""
Sandbox: compare two methods to build articles_unique.

Method A (timestamp):
- Keep the row with the most recent timestamp parsed from xml_source_file.

Method B (prefer by year):
- Prefer rows whose xml_source_file contains 'EFETCH_BY_YEAR'.
- Tie-breaker: xml_source_file descending (stable).

Outputs:
- Prints summary comparison metrics (redirect to TXT if desired).
- Saves a CSV with the PMIDs where the chosen xml_source_file differs.
"""

from pathlib import Path
import pandas as pd
import re


PROJECT_ROOT = Path(".")
INPUT_CSV = PROJECT_ROOT / "data" / "processed" / "articles_all.csv"
OUT_DIFF_CSV = PROJECT_ROOT / "data" / "sandbox" / "articles_unique_method_differences.csv"

TIMESTAMP_PATTERN = re.compile(r"(\d{8}_\d{6})")


def extract_ts(xml_name: str):
    if pd.isna(xml_name):
        return pd.NaT
    m = TIMESTAMP_PATTERN.search(str(xml_name))
    if not m:
        return pd.NaT
    return pd.to_datetime(m.group(1), format="%Y%m%d_%H%M%S")


def build_method_a(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["extraction_ts"] = x["xml_source_file"].apply(extract_ts) # type: ignore
    x_sorted = x.sort_values(by=["pmid", "extraction_ts", "xml_source_file"], ascending=[True, False, False])
    a = x_sorted.drop_duplicates(subset=["pmid"], keep="first").copy()
    return a.drop(columns=["extraction_ts"])


def build_method_b(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["is_by_year"] = x["xml_source_file"].astype(str).str.contains("EFETCH_BY_YEAR", na=False)
    x_sorted = x.sort_values(by=["pmid", "is_by_year", "xml_source_file"], ascending=[True, False, False])
    b = x_sorted.drop_duplicates(subset=["pmid"], keep="first").copy()
    return b.drop(columns=["is_by_year"])


def main():
    df = pd.read_csv(INPUT_CSV, low_memory=False)

    # basic sanity
    if "pmid" not in df.columns or "xml_source_file" not in df.columns:
        raise ValueError("Expected columns 'pmid' and 'xml_source_file' not found.")

    print("Building articles_unique by Method A (timestamp)...")
    a = build_method_a(df)
    print("Building articles_unique by Method B (prefer EFETCH_BY_YEAR)...")
    b = build_method_b(df)

    print("\nCounts:")
    print(f" - Input rows: {len(df)}")
    print(f" - Method A rows: {len(a)} | distinct pmids: {a['pmid'].nunique()}")
    print(f" - Method B rows: {len(b)} | distinct pmids: {b['pmid'].nunique()}")

    # compare selection per PMID using xml_source_file as the differentiator
    a_sel = a[["pmid", "xml_source_file"]].rename(columns={"xml_source_file": "xml_a"})
    b_sel = b[["pmid", "xml_source_file"]].rename(columns={"xml_source_file": "xml_b"})
    merged = a_sel.merge(b_sel, on="pmid", how="inner")

    diffs = merged[merged["xml_a"] != merged["xml_b"]].copy()

    print("\nComparison:")
    print(f" - PMIDs compared: {len(merged)}")
    print(f" - PMIDs with different chosen xml_source_file: {len(diffs)}")

    if len(diffs) > 0:
        OUT_DIFF_CSV.parent.mkdir(parents=True, exist_ok=True)
        diffs.to_csv(OUT_DIFF_CSV, index=False)
        print(f" - Differences CSV saved to: {OUT_DIFF_CSV}")
        print(" - Sample differences (first 10):")
        print(diffs.head(10).to_string(index=False))
    else:
        print(" - No differences found. Methods are equivalent for selection.")

    print("\nDone.")


if __name__ == "__main__":
    main()
