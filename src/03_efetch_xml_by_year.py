"""
03_efetch_xml_by_year.py

Objetivo:
- Baixar os XML completos dos artigos PubMed (EFetch),
  a partir dos PMIDs coletados previamente por ano.
- Preservar dados brutos completos para parsing posterior.
- Operar com controle de execução, retry, checkpoint e manifesto.

Este script NÃO faz parsing de autores nem gera CSV.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from tqdm import tqdm


# ---------------------------------------------------------------------
# Paths e constantes do projeto
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.env"

ESEARCH_ROOT = PROJECT_ROOT / "data" / "raw" / "esearch_by_year"
EFETCH_ROOT = PROJECT_ROOT / "data" / "raw" / "efetch_by_year"

CHECKPOINTS = PROJECT_ROOT / "runs" / "checkpoints"
MANIFESTS = PROJECT_ROOT / "runs" / "manifests"

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


@dataclass
class EFetchConfig:
    strategy_id: str
    batch_size: int
    timeout_seconds: int
    sleep_seconds: float
    year_start: int
    year_end: int


# ---------------------------------------------------------------------
# Funções utilitárias
# ---------------------------------------------------------------------

def load_pmids_for_year(year_dir: Path) -> list[str]:
    """Carrega todos os PMIDs (JSONs) de um ano e retorna lista única."""
    pmids: list[str] = []
    for json_file in sorted(year_dir.glob("*.json")):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        pmids.extend(data)
    return pmids


def chunk_list(items: list[str], size: int) -> list[list[str]]:
    """Divide lista em blocos de tamanho fixo."""
    return [items[i:i + size] for i in range(0, len(items), size)]


def load_checkpoint(strategy_id: str, year: int) -> tuple[int, Path]:
    checkpoint_path = CHECKPOINTS / f"{strategy_id}_efetch_{year}.json"
    if checkpoint_path.exists():
        data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        return int(data.get("batch_index", 0)), checkpoint_path
    return 0, checkpoint_path


def save_checkpoint(checkpoint_path: Path, batch_index: int) -> None:
    checkpoint_path.write_text(
        json.dumps({"batch_index": batch_index}, indent=2),
        encoding="utf-8"
    )


def efetch_batch(pmids: list[str], cfg: EFetchConfig) -> str:
    """Executa uma chamada EFetch e retorna XML bruto."""
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }

    email = os.getenv("NCBI_EMAIL", "").strip()
    tool = os.getenv("NCBI_TOOL", "pubmed_br_authors_level1").strip()
    api_key = os.getenv("NCBI_API_KEY", "").strip()

    if email:
        params["email"] = email
    if tool:
        params["tool"] = tool
    if api_key:
        params["api_key"] = api_key

    url = f"{EFETCH_URL}?{urlencode(params)}"

    max_retries = 5
    backoff = 2.0
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, timeout=cfg.timeout_seconds)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            last_exc = exc
            wait = backoff * attempt
            print(
                f"WARNING: EFetch failed (attempt {attempt}/{max_retries}). "
                f"Waiting {wait:.1f}s. Error: {type(exc).__name__}: {exc}"
            )
            time.sleep(wait)

    raise RuntimeError("EFetch failed after retries") from last_exc


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    load_dotenv(CONFIG_PATH)

    EFETCH_ROOT.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)

    cfg = EFetchConfig(
        strategy_id="A1_v2_2020_2024_no_trials",
        batch_size=100,
        timeout_seconds=30,
        sleep_seconds=0.4,
        year_start=2020,
        year_end=2024,
    )

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{cfg.strategy_id}_EFETCH_BY_YEAR"

    summary: dict[int, dict] = {}

    for year in range(cfg.year_start, cfg.year_end + 1):
        print(f"\n=== EFetch YEAR {year} ===")

        year_search_dir = ESEARCH_ROOT / str(year)
        if not year_search_dir.exists():
            print(f"WARNING: No ESearch data for year {year}, skipping.")
            continue

        pmids = load_pmids_for_year(year_search_dir)
        batches = chunk_list(pmids, cfg.batch_size)

        year_out_dir = EFETCH_ROOT / str(year)
        year_out_dir.mkdir(parents=True, exist_ok=True)

        start_batch, checkpoint_path = load_checkpoint(cfg.strategy_id, year)

        pbar = tqdm(
            total=len(batches),
            initial=start_batch,
            desc=f"EFetch {year}",
            unit="batch"
        )

        for batch_index in range(start_batch, len(batches)):
            batch_pmids = batches[batch_index]
            xml_text = efetch_batch(batch_pmids, cfg)

            out_file = year_out_dir / f"{run_id}_batch_{batch_index:05d}.xml"
            out_file.write_text(xml_text, encoding="utf-8")

            save_checkpoint(checkpoint_path, batch_index + 1)
            pbar.update(1)

            time.sleep(cfg.sleep_seconds)

        pbar.close()

        summary[year] = {
            "total_pmids": len(pmids),
            "total_batches": len(batches),
            "checkpoint_file": checkpoint_path.name,
            "output_dir": str(year_out_dir),
        }

    manifest = {
        "run_id": run_id,
        "stage": "efetch_xml_by_year",
        "strategy_id": cfg.strategy_id,
        "batch_size": cfg.batch_size,
        "years": list(range(cfg.year_start, cfg.year_end + 1)),
        "summary_by_year": summary,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "source": "PubMed",
    }

    (MANIFESTS / f"{run_id}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("\nEFETCH BY YEAR completed.")
    print("STATUS: OK")


if __name__ == "__main__":
    main()
