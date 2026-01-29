"""
02_esearch_pmids.py

Objetivo (Nível 1 do pipeline):
- Executar uma busca ESearch no PubMed (NCBI E-utilities) para obter PMIDs em lotes paginados.
- Salvar os PMIDs por lote (arquivos incrementais).
- Manter checkpoint (retstart) para retomar exatamente após falhas.
- Registrar manifesto de execução (rastreabilidade).

Por que XML (retmode=xml) em vez de JSON?
- Em coletas longas, respostas JSON podem ocasionalmente vir truncadas ou contaminadas.
- XML do E-utilities é tradicionalmente mais estável e fácil de validar/parsear.
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

DATA_RAW = PROJECT_ROOT / "data" / "raw" / "esearch"
CHECKPOINTS = PROJECT_ROOT / "runs" / "checkpoints"
MANIFESTS = PROJECT_ROOT / "runs" / "manifests"

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


@dataclass
class ESearchConfig:
    """Parâmetros de execução para ESearch."""
    strategy_id: str
    retmax: int
    timeout_seconds: int
    sleep_seconds: float


def load_query_from_latest_manifest(strategy_id: str) -> tuple[str, Path]:
    """
    Carrega a query a partir do manifesto mais recente de BUILDQUERY
    correspondente ao strategy_id.

    Retorna:
      - query (str)
      - path do manifesto (Path)
    """
    build_manifests = sorted(MANIFESTS.glob(f"*{strategy_id}*BUILDQUERY.json"))
    if not build_manifests:
        raise FileNotFoundError(
            f"Nenhum manifesto BUILDQUERY encontrado para strategy_id={strategy_id} em {MANIFESTS}"
        )

    query_manifest_path = build_manifests[-1]
    query_data = json.loads(query_manifest_path.read_text(encoding="utf-8"))
    query = query_data["query"]
    return query, query_manifest_path


def load_checkpoint(strategy_id: str) -> tuple[int, Path]:
    """
    Checkpoint guarda o estado mutável da execução (onde parou).
    Se existir, retomamos a partir do retstart salvo.
    """
    checkpoint_path = CHECKPOINTS / f"{strategy_id}_esearch.json"
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        return int(checkpoint.get("retstart", 0)), checkpoint_path
    return 0, checkpoint_path


def save_checkpoint(checkpoint_path: Path, retstart: int) -> None:
    """Salva o retstart atual (estado mutável de retomada)."""
    checkpoint_path.write_text(json.dumps({"retstart": retstart}, indent=2), encoding="utf-8")


def parse_esearch_xml(xml_bytes: bytes) -> tuple[int, list[str]]:
    """
    Faz parsing do XML do ESearch e retorna:
      - count: total de resultados da query (para barra de progresso)
      - idlist: lista de PMIDs do lote atual
    """
    root = etree.fromstring(xml_bytes)

    count_text = root.findtext("Count") or "0"
    count = int(count_text)

    idlist = [elem.text for elem in root.findall(".//IdList/Id") if elem.text]
    return count, idlist


def build_request_params(query: str, retstart: int, cfg: ESearchConfig) -> dict:
    """
    Parâmetros do ESearch.
    Usamos retmode=xml por robustez.
    """
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "xml",
        "retmax": cfg.retmax,
        "retstart": retstart,
    }

    # Boas práticas NCBI: identificar o client quando possível
    # (não é obrigatório, mas é recomendado)
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


def request_esearch(query: str, retstart: int, cfg: ESearchConfig) -> tuple[int, list[str]]:
    """
    Faz a requisição ESearch e retorna (count, idlist).
    Implementa retry simples para lidar com falhas transitórias (rede, throttle, resposta truncada).
    """
    params = build_request_params(query, retstart, cfg)
    url = f"{ESEARCH_URL}?{urlencode(params)}"

    max_retries = 6
    backoff = 2.0

    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, timeout=cfg.timeout_seconds)
            resp.raise_for_status()

            # Se o XML vier inválido/truncado, etree.fromstring pode falhar.
            count, idlist = parse_esearch_xml(resp.content)
            return count, idlist

        except Exception as exc:
            # Decisão de engenharia:
            # - não quebrar o pipeline por falha transitória
            # - esperar um pouco e tentar novamente
            last_exc = exc
            wait = backoff * attempt
            print(
                f"WARNING: ESearch failed (attempt {attempt}/{max_retries}) at retstart={retstart}. "
                f"Waiting {wait:.1f}s then retry. Error: {type(exc).__name__}: {exc}"
            )
            time.sleep(wait)

    # Se chegou aqui, falhou de forma persistente
    raise RuntimeError(f"ESearch failed after {max_retries} retries at retstart={retstart}") from last_exc


def main() -> None:
    # Carrega configurações externas (parâmetros e credenciais)
    load_dotenv(CONFIG_PATH)

    # Garante diretórios de output/estado
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)

    # Config do estágio (ajuste aqui se necessário)
    cfg = ESearchConfig(
        strategy_id="A1_v2_2020_2024_no_trials",
        retmax=int(os.getenv("RETMAX", "200")),
        timeout_seconds=int(os.getenv("TIMEOUT_SECONDS", "30")),
        sleep_seconds=0.34,  # throttle gentil (evita sobrecarregar o NCBI)
    )

    # Retomar a partir do checkpoint, se houver
    retstart, checkpoint_path = load_checkpoint(cfg.strategy_id)

    # Carrega a query do manifesto BUILDQUERY mais recente
    query, query_manifest_path = load_query_from_latest_manifest(cfg.strategy_id)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{cfg.strategy_id}_ESEARCH"

    # A barra de progresso precisa do total (Count). Pegamos no primeiro request.
    total_count = None
    pbar = None

    collected_total = 0

    while True:
        count, idlist = request_esearch(query=query, retstart=retstart, cfg=cfg)

        # Inicializa barra apenas na primeira resposta válida
        if total_count is None:
            total_count = count
            pbar = tqdm(total=total_count, desc="PMIDs (ESearch)", unit="pmid")

        # Se não vier mais nada, encerramos
        if not idlist:
            break

        batch_id = f"retstart_{retstart}"
        out_path = DATA_RAW / f"{run_id}_{batch_id}.json"
        out_path.write_text(json.dumps(idlist, indent=2), encoding="utf-8")

        # Atualiza progresso e checkpoint
        if pbar is not None:
            pbar.update(len(idlist))

        collected_total += len(idlist)

        retstart += cfg.retmax
        save_checkpoint(checkpoint_path, retstart)

        # Heartbeat para o terminal (útil mesmo sem tqdm)
        print(f"Collected {len(idlist)} PMIDs (next retstart={retstart})")

        # Throttle para respeitar o serviço e reduzir chance de respostas inválidas
        time.sleep(cfg.sleep_seconds)

    # Fecha barra
    if pbar is not None:
        pbar.close()

    # Manifesto final da execução
    manifest = {
        "run_id": run_id,
        "stage": "esearch_pmids",
        "strategy_id": cfg.strategy_id,
        "query_manifest": query_manifest_path.name,
        "retmax": cfg.retmax,
        "final_retstart": retstart,
        "collected_total_pmids": collected_total,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "source": "PubMed",
    }

    (MANIFESTS / f"{run_id}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("ESEARCH completed.")
    print("STATUS: OK")


if __name__ == "__main__":
    main()
