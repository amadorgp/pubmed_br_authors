from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.env"
RUNS_MANIFESTS = PROJECT_ROOT / "runs" / "manifests"


def build_query(strategy_id: str) -> str:
    """
    Estratégia A1 v2:
    - Afiliação Brasil
    - Humanos
    - Período 2020–2024
    - Exclusão de ensaios clínicos
    """
    brazil_affil = 'Brazil[Affiliation] OR Brasil[Affiliation]'
    date_range = '"2020/01/01"[Date - Publication] : "2024/12/31"[Date - Publication]'
    humans = 'Humans[MeSH Terms]'
    no_trials = 'NOT (Clinical Trial[pt] OR Randomized Controlled Trial[pt] OR Controlled Clinical Trial[pt])'

    query = f"({brazil_affil}) AND ({date_range}) AND ({humans}) {no_trials}"
    return query


def main():
    load_dotenv(CONFIG_PATH)

    strategy_id = "A1_v2_2020_2024_no_trials"
    query = build_query(strategy_id)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{strategy_id}_BUILDQUERY"
    RUNS_MANIFESTS.mkdir(parents=True, exist_ok=True)
    manifest_path = RUNS_MANIFESTS / f"{run_id}.json"

    manifest = {
        "run_id": run_id,
        "stage": "build_query_only",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "strategy_id": strategy_id,
        "query": query,
        "notes": "This run only builds and records the PubMed query. No API calls executed.",
        "config_loaded": str(CONFIG_PATH),
        "ncbi_email_present": bool(os.getenv("NCBI_EMAIL")),
        "ncbi_tool": os.getenv("NCBI_TOOL", "pubmed_br_authors_level1"),
    }

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("Strategy:", strategy_id)
    print("Query:\n", query)
    print("Manifest written:", manifest_path)
    print("STATUS: OK")


if __name__ == "__main__":
    main()
