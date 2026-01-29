"""
05_merge_csvs.py

Objetivo:
- Unificar CSVs anuais em arquivos únicos:
  - articles_all.csv
  - author_occurrences_all.csv

Observações:
- Não faz deduplicação
- Mantém ordem dos arquivos por ano
- Preserva headers corretamente
"""

from pathlib import Path
import csv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_ROOT / "data" / "processed"

OUT_ARTICLES = PROCESSED / "articles_all.csv"
OUT_AUTHORS = PROCESSED / "author_occurrences_all.csv"


def merge_csv(pattern: str, output_path: Path) -> None:
    files = sorted(PROCESSED.glob(pattern))
    if not files:
        print(f"WARNING: no files found for pattern {pattern}")
        return

    print(f"Merging {len(files)} files into {output_path.name}")

    with open(output_path, "w", newline="", encoding="utf-8") as fout:
        writer = None

        for i, fpath in enumerate(files):
            with open(fpath, "r", encoding="utf-8") as fin:
                reader = csv.DictReader(fin)

                if writer is None:
                    writer = csv.DictWriter(fout, fieldnames=reader.fieldnames) # type: ignore
                    writer.writeheader()

                for row in reader:
                    writer.writerow(row)

    print(f"OK: {output_path.name} created")


def main() -> None:
    merge_csv("articles_*.csv", OUT_ARTICLES)
    merge_csv("author_occurrences_*.csv", OUT_AUTHORS)


if __name__ == "__main__":
    main()
