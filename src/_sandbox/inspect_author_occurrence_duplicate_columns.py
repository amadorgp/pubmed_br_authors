"""
Sandbox: inspect which columns differ within duplicated (pmid, author_position) groups.

This answers:
- Are duplicates identical except xml_source_file?
- If not, which columns differ (e.g., affiliation_raw, author_name_raw, etc.)?

Output is printed; recommend redirect to TXT.
"""

from pathlib import Path
import pandas as pd


PROJECT_ROOT = Path(".")
INPUT_CSV = PROJECT_ROOT / "data" / "processed" / "author_occurrences_all.csv"


def main() -> None:
    df = pd.read_csv(INPUT_CSV, low_memory=False)

    required = ["pmid", "author_position", "xml_source_file"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    key = ["pmid", "author_position"]

    # Find duplicated keys
    counts = df.groupby(key, dropna=False).size().reset_index(name="n")
    dup = counts[counts["n"] > 1].copy()

    print("INSPECT DUPLICATED (pmid, author_position) GROUPS")
    print("================================================")
    print(f"Total rows: {len(df)}")
    print(f"Duplicated keys: {len(dup)}")

    if len(dup) == 0:
        print("No duplicated keys found. Done.")
        return

    # pick first duplicated key (you can change idx)
    sample = dup.iloc[0]
    pmid_val = sample["pmid"]
    pos_val = sample["author_position"]

    subset = df[(df["pmid"] == pmid_val) & (df["author_position"] == pos_val)].copy()

    print("\nSample duplicated key:")
    print(f"pmid={pmid_val} | author_position={pos_val} | rows={len(subset)}")

    print("\nxml_source_file values:")
    print(subset["xml_source_file"].astype(str).value_counts().to_string())

    # Identify differing columns
    differing_cols = []
    for col in df.columns:
        nun = subset[col].nunique(dropna=False)
        if nun > 1:
            differing_cols.append(col)

    print("\nColumns that differ within this duplicated group:")
    if differing_cols:
        print(differing_cols)
    else:
        print("None (rows are identical across all columns).")

    # Show values for each differing column
    for col in differing_cols:
        print(f"\n--- {col} ---")
        vals = subset[col].astype(str).unique()
        for v in vals:
            print(v)

    # Strong check: identical except xml_source_file
    cols_except_source = [c for c in df.columns if c != "xml_source_file"]
    rows_identical_except_source = subset[cols_except_source].nunique(dropna=False).max() == 1
    print(f"\nRows identical except xml_source_file? {rows_identical_except_source}")

    print("\nDone.")


if __name__ == "__main__":
    main()
