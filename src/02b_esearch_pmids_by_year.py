"""
02b_esearch_pmids_by_year.py

Objetivo:
- Contornar o limite prático do ESearch (~10.000 registros por query grande no PubMed)
  dividindo a coleta em fatias menores por ano (2020–2024).
- Cada ano gera:
  - PMIDs por lote (JSON)
  - checkpoint (retstart)
  - manifesto final

Boas práticas implementadas:
- retmode=xml (mais robusto)
- retry com backoff
- checkpoint por ano (retoma sem reprocessar)
- outputs incrementais (lote a lote)
- tqdm para visibilidade
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
from lxml import etree # type: ignore
from tqdm import tqdm


# --- Paths e constantes do projeto -------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.env"

DATA_ROOT = PROJECT_ROOT / "data" / "raw" / "esearch_by_year"
CHECKPOINTS = PROJECT_ROOT / "runs" / "checkpoints"
MANIFESTS = PROJECT_ROOT / "runs" / "manifests"

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


@dataclass
class ESearchConfig:
    strategy_id: str
    retmax: int
    timeout_seconds: int
    sleep_seconds: float
    year_start: int
    year_end: int


def parse_esearch_xml(xml_bytes: bytes) -> tuple[int, list[str]]:
    root = etree.fromstring(xml_bytes)
    count_text = root.findtext("Count") or "0"
    count = int(count_text)
    idlist = [e.text for e in root.findall(".//IdList/Id") if e.text]
    return count, idlist


def build_query_for_year(base_query: str, year: int) -> str:
    """
    PubMed: filtro por data de publicação usando Date - Publication.
    Aqui fazemos janela anual: 01/01 a 12/31 do ano.
    """
    date_range = f'"{year}/01/01"[Date - Publication] : "{year}/12/31"[Date - Publication]'
    return f"({base_query}) AND ({date_range})"


def build_request_params(query: str, retstart: int, cfg: ESearchConfig) -> dict:
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "xml",
        "retmax": cfg.retmax,
        "retstart": retstart,
    }

    # Identificação recomendada pelo NCBI
    email = os.getenv("NCBI_EMAIL", "").strip()
    tool = os.getenv("NCBI_TOOL", "pubmed_br_authors_level1").strip()
    api_key = os.getenv("NCBI_API_KEY", "").strip()

    if email:
        params["email"] = email
    if tool:
        params["tool"] = tool
    if api_key:
        params["api_key"] = api_key

    return params


def request_esearch(query: str, retstart: int, cfg: ESearchConfig, year: int) -> tuple[int, list[str]]:
    params = build_request_params(query, retstart, cfg)
    url = f"{ESEARCH_URL}?{urlencode(params)}"

    max_retries = 6
    backoff = 2.0
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, timeout=cfg.timeout_seconds)
            resp.raise_for_status()
            return parse_esearch_xml(resp.content)

        except Exception as exc:
            last_exc = exc
            wait = backoff * attempt
            print(
                f"WARNING: ESearch failed (year={year}, attempt {attempt}/{max_retries}) "
                f"at retstart={retstart}. Waiting {wait:.1f}s. Error: {type(exc).__name__}: {exc}"
            )
            time.sleep(wait)

    raise RuntimeError(f"ESearch failed after {max_retries} retries (year={year}, retstart={retstart})") from last_exc


def load_base_query(strategy_id: str) -> tuple[str, Path]:
    """
    Usa o manifesto BUILDQUERY mais recente da estratégia escolhida.
    OBS: Esse manifesto deve existir porque você já rodou o 01_build_query.py.
    """
    build_manifests = sorted(MANIFESTS.glob(f"*{strategy_id}*BUILDQUERY.json"))
    if not build_manifests:
        raise FileNotFoundError(
            f"Nenhum manifesto BUILDQUERY encontrado para strategy_id={strategy_id} em {MANIFESTS}"
        )

    query_manifest_path = build_manifests[-1]
    query_data = json.loads(query_manifest_path.read_text(encoding="utf-8"))
    return query_data["query"], query_manifest_path


def load_checkpoint(strategy_id: str, year: int) -> tuple[int, Path]:
    checkpoint_path = CHECKPOINTS / f"{strategy_id}_esearch_{year}.json"
    if checkpoint_path.exists():
        data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        return int(data.get("retstart", 0)), checkpoint_path
    return 0, checkpoint_path


def save_checkpoint(checkpoint_path: Path, retstart: int) -> None:
    checkpoint_path.write_text(json.dumps({"retstart": retstart}, indent=2), encoding="utf-8")


def main() -> None:
    load_dotenv(CONFIG_PATH)

    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)

    cfg = ESearchConfig(
        strategy_id="A1_v2_2020_2024_no_trials",
        retmax=int(os.getenv("RETMAX", "200")),
        timeout_seconds=int(os.getenv("TIMEOUT_SECONDS", "30")),
        sleep_seconds=0.34,
        year_start=2020,
        year_end=2024,
    )

    base_query, base_manifest_path = load_base_query(cfg.strategy_id)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{cfg.strategy_id}_ESEARCH_BY_YEAR"

    yearly_summary: dict[int, dict] = {}

    for year in range(cfg.year_start, cfg.year_end + 1):
        print(f"\n=== YEAR {year} ===")

        year_dir = DATA_ROOT / str(year)
        year_dir.mkdir(parents=True, exist_ok=True)

        year_query = build_query_for_year(base_query, year)
        retstart, checkpoint_path = load_checkpoint(cfg.strategy_id, year)

        total_count = None
        pbar = None
        collected_total = 0

        while True:
            count, idlist = request_esearch(query=year_query, retstart=retstart, cfg=cfg, year=year)

            if total_count is None:
                total_count = count
                pbar = tqdm(total=total_count, desc=f"PMIDs {year}", unit="pmid")

            if not idlist:
                break

            batch_id = f"retstart_{retstart}"
            out_path = year_dir / f"{run_id}_{year}_{batch_id}.json"
            out_path.write_text(json.dumps(idlist, indent=2), encoding="utf-8")

            if pbar is not None:
                pbar.update(len(idlist))

            collected_total += len(idlist)

            retstart += cfg.retmax
            save_checkpoint(checkpoint_path, retstart)

            print(f"Collected {len(idlist)} PMIDs (year={year}, next retstart={retstart})")
            time.sleep(cfg.sleep_seconds)

        if pbar is not None:
            pbar.close()

        yearly_summary[year] = {
            "count_reported_by_ncbi": total_count or 0,
            "collected_total_pmids": collected_total,
            "final_retstart": retstart,
            "checkpoint_file": checkpoint_path.name,
            "output_dir": str(year_dir),
        }

    manifest = {
        "run_id": run_id,
        "stage": "esearch_pmids_by_year",
        "strategy_id": cfg.strategy_id,
        "base_query_manifest": base_manifest_path.name,
        "years": list(range(cfg.year_start, cfg.year_end + 1)),
        "retmax": cfg.retmax,
        "summary_by_year": yearly_summary,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "source": "PubMed",
    }

    (MANIFESTS / f"{run_id}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("\nESEARCH BY YEAR completed.")
    print("STATUS: OK")


if __name__ == "__main__":
    main()
