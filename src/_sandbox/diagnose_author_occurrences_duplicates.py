"""
Sandbox: diagnose technical duplicates in author_occurrences_all.csv.

Goal
----
Check whether there are technical duplicates likely caused by duplicated article
extraction events, focusing on the natural key of an author occurrence.

Natural key (for this project)
------------------------------
(pmid, author_position)

We avoid ORCID because it's not consistently present and would bias the dataset.

Outputs
-------
This script prints summary stats. Recommend redirecting stdout to a TXT in:
data/sandbox/diagnose_authors_duplicates.txt
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
        raise ValueError(f"Missing required columns in author_occurrences_all.csv: {missing}")

    total_rows = len(df)
    distinct_pmids = df["pmid"].nunique(dropna=True)

    # Natural key
    key = ["pmid", "author_position"]
    distinct_key = df[key].drop_duplicates().shape[0]

    # Count duplicated keys
    dup_key_counts = (
        df.groupby(key, dropna=False)
          .size()
          .reset_index(name="n")
    )
    duplicated_keys = dup_key_counts[dup_key_counts["n"] > 1]

    print("AUTHOR_OCCURRENCES DUPLICATE DIAGNOSIS (SANDBOX)")
    print("==============================================")
    print(f"Input file: {INPUT_CSV}")
    print(f"Total rows: {total_rows}")
    print(f"Distinct PMIDs: {distinct_pmids}")
    print(f"Distinct (pmid, author_position): {distinct_key}")
    print(f"Duplicated (pmid, author_position) keys: {len(duplicated_keys)}")

    if len(duplicated_keys) > 0:
        print("\nSample duplicated keys (first 20):")
        print(duplicated_keys.head(20).to_string(index=False))

        # Pull a concrete example to see if duplicates are explained only by xml_source_file
        sample = duplicated_keys.iloc[0]
        pmid_val = sample["pmid"]
        pos_val = sample["author_position"]

        subset = df[(df["pmid"] == pmid_val) & (df["author_position"] == pos_val)]

        print("\nExample duplicated occurrence:")
        print(f"pmid={pmid_val} | author_position={pos_val} | rows={len(subset)}")

        # show which source files produced the duplicate
        print("xml_source_file values for this occurrence:")
        print(subset["xml_source_file"].astype(str).value_counts().to_string())

        # check whether rows are identical apart from xml_source_file
        cols_to_compare = [c for c in df.columns if c != "xml_source_file"]
        identical_except_source = subset[cols_to_compare].duplicated().all()
        print(f"Rows identical except xml_source_file? {identical_except_source}")

    print("\nDone.")


if __name__ == "__main__":
    main()
