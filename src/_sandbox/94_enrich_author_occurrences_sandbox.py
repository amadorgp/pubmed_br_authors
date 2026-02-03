"""
94_enrich_author_occurrences_sandbox.py

Purpose
-------
Create non-destructive, row-level enrichment features for author occurrences:
- email extraction from affiliation text
- Brazilian state (UF) extraction from affiliation text (very conservative)

Input
-----
data/processed/author_occurrences_unique.csv

Output
------
data/processed/author_occurrences_enriched.csv

Notes
-----
Sandbox script: validate outputs before promoting to src/.
No merges, no ID creation. Only adds columns.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Enrich author_occurrences_unique with derived features.")
    p.add_argument("--project-root", required=True)
    p.add_argument("--input-csv", default="data/processed/author_occurrences_unique.csv")
    p.add_argument("--output-csv", default="data/processed/author_occurrences_enriched.csv")
    return p.parse_args()


EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

STATE_PATTERNS = {
    "AC": r"\bAC\b|\bAcre\b",
    "AL": r"\bAL\b|\bAlagoas\b",
    "AP": r"\bAP\b|\bAmap[aá]\b",
    "AM": r"\bAM\b|\bAmazonas\b",
    "BA": r"\bBA\b|\bBahia\b",
    "CE": r"\bCE\b|\bCear[aá]\b",
    "DF": r"\bDF\b|\bDistrito Federal\b",
    "ES": r"\bES\b|\bEsp[ií]rito Santo\b",
    "GO": r"\bGO\b|\bGoi[aá]s\b",
    "MA": r"\bMA\b|\bMaranh[aã]o\b",
    "MT": r"\bMT\b|\bMato Grosso\b",
    "MS": r"\bMS\b|\bMato Grosso do Sul\b",
    "MG": r"\bMG\b|\bMinas Gerais\b",
    "PA": r"\bPA\b|\bPar[aá]\b",
    "PB": r"\bPB\b|\bPara[ií]ba\b",
    "PR": r"\bPR\b|\bParan[aá]\b",
    "PE": r"\bPE\b|\bPernambuco\b",
    "PI": r"\bPI\b|\bPiau[ií]\b",
    "RJ": r"\bRJ\b|\bRio de Janeiro\b",
    "RN": r"\bRN\b|\bRio Grande do Norte\b",
    "RS": r"\bRS\b|\bRio Grande do Sul\b",
    "RO": r"\bRO\b|\bRond[oô]nia\b",
    "RR": r"\bRR\b|\bRoraima\b",
    "SC": r"\bSC\b|\bSanta Catarina\b",
    "SP": r"\bSP\b|\bS[aã]o Paulo\b",
    "SE": r"\bSE\b|\bSergipe\b",
    "TO": r"\bTO\b|\bTocantins\b",
}


def extract_email(text: str | None) -> str | None:
    if not isinstance(text, str):
        return None
    match = EMAIL_REGEX.search(text)
    return match.group(0).lower() if match else None


def extract_br_state(text: str | None) -> str | None:
    if not isinstance(text, str):
        return None
    for uf, pattern in STATE_PATTERNS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            return uf
    return None


def main() -> None:
    args = parse_args()
    root = Path(args.project_root)

    input_path = root / args.input_csv
    output_path = root / args.output_csv

    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    df = pd.read_csv(input_path, low_memory=False)

    # Add derived columns (non-destructive)
    df["email_extracted"] = df["affiliation_raw"].apply(extract_email)
    df["affiliation_state_extracted"] = df["affiliation_raw"].apply(extract_br_state)

    df.to_csv(output_path, index=False, encoding="utf-8")

    # Minimal validation printout
    email_count = int(df["email_extracted"].notna().sum())
    state_count = int(df["affiliation_state_extracted"].notna().sum())
    print(f"✅ Enriched CSV exported: {output_path}")
    print(f"   - emails extracted: {email_count}")
    print(f"   - states extracted: {state_count}")


if __name__ == "__main__":
    main()
