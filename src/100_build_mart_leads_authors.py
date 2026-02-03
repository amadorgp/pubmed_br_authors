"""
100_build_mart_leads_authors.py

Constrói o mart final de consumo por author_cluster_id (Opção A auditável).

Entrada:
- data/processed/author_occurrences_enriched_n2_resolved.csv

Saídas (não destrutivas):
- data/processed/mart_leads_authors.csv                 (tabela 1 linha por author_cluster_id)
- data/processed/mart_leads_authors__sources.csv        (opcional: distribuição de fontes por cluster, se existir 'source')

Rastreabilidade:
- runs/logs/<run_id>_100_build_mart_leads_authors.log
- runs/manifests/<run_id>_100_build_mart_leads_authors.json

Princípios:
- author_cluster_id é a identidade analítica.
- Mantém auditabilidade: você sempre volta do mart para a base de ocorrências via author_cluster_id.
- Não usa e-mail/afiliação para "decisão" — apenas para enriquecer a lista final de leads (quando disponível).
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd


# -----------------------------
# Paths (root implícito)
# -----------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
RUNS_DIR = PROJECT_ROOT / "runs"
RUNS_LOGS = RUNS_DIR / "logs"
RUNS_MANIFESTS = RUNS_DIR / "manifests"


# -----------------------------
# Manifest
# -----------------------------
@dataclass
class Manifest:
    step_id: str
    run_id: str
    run_ts: str
    input_path: str
    output_mart_path: str
    output_sources_path: Optional[str]
    input_shape: tuple[int, int]
    output_shape: tuple[int, int]
    n_author_clusters: int
    n_rows_with_null_cluster_id: int
    columns_out: list[str]
    notes: str


# -----------------------------
# Utilities
# -----------------------------
def _now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _ensure_dirs() -> None:
    RUNS_LOGS.mkdir(parents=True, exist_ok=True)
    RUNS_MANIFESTS.mkdir(parents=True, exist_ok=True)


def _log_line(log_path: Path, msg: str) -> None:
    with log_path.open("a", encoding="utf-8") as f:
        f.write(msg.rstrip() + "\n")


def most_frequent(series: pd.Series) -> Optional[Any]:
    """Retorna o valor mais frequente (moda). Ignora NaN. Se vazio, retorna None."""
    if series is None:
        return None
    s = series.dropna()
    if s.empty:
        return None
    # value_counts ordena por frequência desc; idxmax pega a primeira moda
    return s.value_counts().idxmax()


def any_notna(series: pd.Series) -> bool:
    s = series
    if s is None:
        return False
    return bool(s.notna().any())


def safe_nunique(series: pd.Series) -> int:
    s = series.dropna()
    return int(s.nunique())


def safe_bool_any_equals(series: pd.Series, target: str) -> bool:
    s = series.dropna()
    if s.empty:
        return False
    return bool((s == target).any())


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    _ensure_dirs()

    step_id = "100_build_mart_leads_authors"
    run_ts = _now_ts()
    run_id = f"{run_ts}_{_short_hash(step_id + run_ts)}"

    input_path = DATA_PROCESSED / "author_occurrences_enriched_n2_resolved.csv"
    output_mart_path = DATA_PROCESSED / "mart_leads_authors.csv"
    output_sources_path = DATA_PROCESSED / "mart_leads_authors__sources.csv"

    log_path = RUNS_LOGS / f"{run_id}_{step_id}.log"
    manifest_path = RUNS_MANIFESTS / f"{run_id}_{step_id}.json"

    if not input_path.exists():
        raise FileNotFoundError(f"Input não encontrado: {input_path}")

    _log_line(log_path, f"[START] {step_id} | run_id={run_id}")
    _log_line(log_path, f"Input: {input_path}")

    df = pd.read_csv(input_path, low_memory=False)
    in_shape = df.shape
    _log_line(log_path, f"Input shape: {in_shape}")

    # -----------------------------
    # Validations
    # -----------------------------
    required = ["author_cluster_id", "pmid"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes: {missing}")

    null_cluster = int(df["author_cluster_id"].isna().sum())
    _log_line(log_path, f"Null author_cluster_id rows: {null_cluster}")

    if null_cluster > 0:
        # Conservador: não falha automaticamente. Mas registra alerta forte.
        _log_line(
            log_path,
            "[WARN] Existem linhas sem author_cluster_id. "
            "O mart manterá essas linhas como um grupo NaN, o que pode ser indesejado no BI. "
            "Ideal: garantir mapeamento completo no step 99.",
        )

    # Normalização mínima de tipo
    df["pmid"] = df["pmid"].astype(str)

    # -----------------------------
    # Grouping
    # -----------------------------
    grp = df.groupby("author_cluster_id", dropna=False)

    # Colunas auditáveis (se existirem)
    has_author_name_raw = "author_name_raw" in df.columns
    has_block_key = "block_key" in df.columns
    has_cluster_size = "author_cluster_size" in df.columns

    # Enrich optional fields (se existirem)
    has_email = "email_extracted" in df.columns
    has_state = "affiliation_state_extracted" in df.columns
    has_source = "source" in df.columns
    has_author_role = "author_role" in df.columns

    # -----------------------------
    # Build mart (1 linha por cluster)
    # -----------------------------
    mart = pd.DataFrame({
        "author_cluster_id": grp.size().index,
        "n_occurrences": grp.size().values,             # linhas (autor-artigo) na base
        "n_articles": grp["pmid"].apply(safe_nunique).values,  # artigos distintos
    })

    if has_cluster_size:
        mart["author_cluster_size"] = grp["author_cluster_size"].max().values

    # Nome canônico (auditoria / display)
    if has_author_name_raw:
        mart["canonical_author_name"] = grp["author_name_raw"].apply(most_frequent).values
    else:
        mart["canonical_author_name"] = None

    # Exemplo de block_key para auditoria rápida
    if has_block_key:
        mart["block_key_example"] = grp["block_key"].apply(most_frequent).values

    # Flags úteis para lead-list (opcionais)
    if has_email:
        mart["any_email"] = grp["email_extracted"].apply(any_notna).values
        mart["email_example"] = grp["email_extracted"].apply(most_frequent).values

    if has_state:
        mart["any_br_affiliation"] = grp["affiliation_state_extracted"].apply(any_notna).values
        mart["state_example"] = grp["affiliation_state_extracted"].apply(most_frequent).values

    # Autor "first" como possível sinal útil (se existir)
    if has_author_role:
        mart["any_first_author"] = grp["author_role"].apply(lambda s: safe_bool_any_equals(s, "first")).values

    # Fonte (se existir): manter como referência
    if has_source:
        mart["source_example"] = grp["source"].apply(most_frequent).values

    # Ordenação: autores com mais artigos primeiro (bom para inspeção)
    mart = mart.sort_values(by=["n_articles", "n_occurrences"], ascending=[False, False]).reset_index(drop=True)

    out_shape = mart.shape
    _log_line(log_path, f"Mart output shape: {out_shape}")

    # -----------------------------
    # Save mart
    # -----------------------------
    mart.to_csv(output_mart_path, index=False)
    _log_line(log_path, f"Saved mart: {output_mart_path}")

    # -----------------------------
    # Optional: sources distribution per cluster (se 'source' existir)
    # -----------------------------
    sources_written: Optional[str] = None
    if has_source:
        # Distribuição simples: para cada cluster, quais fontes aparecem e quantos artigos (pmid) por fonte
        tmp = (
            df[["author_cluster_id", "source", "pmid"]]
            .dropna(subset=["source"])
            .drop_duplicates()
            .groupby(["author_cluster_id", "source"])["pmid"]
            .nunique()
            .reset_index(name="n_articles_by_source")
            .sort_values(["author_cluster_id", "n_articles_by_source"], ascending=[True, False])
        )
        tmp.to_csv(output_sources_path, index=False)
        sources_written = str(output_sources_path)
        _log_line(log_path, f"Saved sources: {output_sources_path}")
    else:
        _log_line(log_path, "No 'source' column found; skipping sources output.")

    # -----------------------------
    # Manifest
    # -----------------------------
    manifest = Manifest(
        step_id=step_id,
        run_id=run_id,
        run_ts=run_ts,
        input_path=str(input_path),
        output_mart_path=str(output_mart_path),
        output_sources_path=sources_written,
        input_shape=in_shape,
        output_shape=out_shape,
        n_author_clusters=int(mart["author_cluster_id"].nunique(dropna=False)),
        n_rows_with_null_cluster_id=null_cluster,
        columns_out=list(mart.columns),
        notes="Consumption mart aggregated by author_cluster_id (auditável).",
    )

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(asdict(manifest), f, ensure_ascii=False, indent=2)

    _log_line(log_path, f"Manifest: {manifest_path}")
    _log_line(log_path, f"[END] {step_id} | run_id={run_id}")

    print(f"OK: {step_id}")
    print(f"Input:  {input_path} | shape={in_shape}")
    print(f"Output: {output_mart_path} | shape={out_shape}")
    if sources_written:
        print(f"Output2:{output_sources_path} | (sources by cluster)")
    print(f"Log:    {log_path.name}")
    print(f"Manifest:{manifest_path.name}")


if __name__ == "__main__":
    main()
