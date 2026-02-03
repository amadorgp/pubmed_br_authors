"""
98_build_author_coauthors_n2.py

N2 (coautores) — derivar métricas simples e robustas baseadas exclusivamente em coautoria.
- Input:  data/processed/author_occurrences_enriched.csv
- Output: data/processed/author_occurrences_enriched_n2.csv

Regras:
- NÃO usar email/afiliação/orcid como sinal.
- NÃO alterar colunas existentes: apenas adicionar colunas derivadas.
- Um passo por vez (execução + checagens).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import hashlib

import pandas as pd


# -----------------------------
# Config / Paths
# -----------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
RUNS_DIR = PROJECT_ROOT / "runs"
RUNS_LOGS = RUNS_DIR / "logs"
RUNS_MANIFESTS = RUNS_DIR / "manifests"


@dataclass
class Manifest:
    step_id: str
    run_ts: str
    input_path: str
    output_path: str
    input_shape: tuple[int, int]
    output_shape: tuple[int, int]
    notes: str


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


def main() -> None:
    _ensure_dirs()

    step_id = "98_build_author_coauthors_n2"
    run_ts = _now_ts()
    run_id = f"{run_ts}_{_short_hash(step_id + run_ts)}"

    input_path = DATA_PROCESSED / "author_occurrences_enriched.csv"
    output_path = DATA_PROCESSED / "author_occurrences_enriched_n2.csv"

    log_path = RUNS_LOGS / f"{run_id}_{step_id}.log"
    manifest_path = RUNS_MANIFESTS / f"{run_id}_{step_id}.json"

    if not input_path.exists():
        raise FileNotFoundError(f"Input não encontrado: {input_path}")

    _log_line(log_path, f"[START] {step_id} | run_id={run_id}")
    _log_line(log_path, f"Input: {input_path}")

    # -----------------------------
    # Load
    # -----------------------------
    df = pd.read_csv(input_path)

    required_cols = ["pmid", "block_key"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes: {missing}")

    in_shape = df.shape
    _log_line(log_path, f"Input shape: {in_shape}")

    # Normalização mínima (sem inventar nada):
    # - pmid pode vir como int/str; tratamos como str para consistência
    # - block_key como str
    df["pmid"] = df["pmid"].astype(str)
    df["block_key"] = df["block_key"].astype(str)

    # -----------------------------
    # Build coauthor metrics (N2)
    # -----------------------------
    # Para cada PMID: conjunto único de autores (block_key)
    pmid_authors = (
        df[["pmid", "block_key"]]
        .dropna()
        .drop_duplicates()
        .groupby("pmid")["block_key"]
        .apply(list)
    )

    # Vamos acumular:
    # - n_unique_coauthors: número de coautores únicos (em todos os artigos)
    # - n_articles: número de artigos únicos em que o autor aparece
    # - n_coauthor_edges: soma (por artigo) de (num_autores_no_artigo - 1)
    #
    # Tudo derivado EXCLUSIVAMENTE de coautoria por pmid.
    author_to_coauthors: dict[str, set[str]] = {}
    author_n_articles: dict[str, int] = {}
    author_coauthor_edges: dict[str, int] = {}

    for pmid, authors in pmid_authors.items():
        # unique no artigo
        a = list(dict.fromkeys(authors))
        if len(a) == 0:
            continue

        for author in a:
            author_n_articles[author] = author_n_articles.get(author, 0) + 1

            # edges por artigo: total_coauthors_no_artigo = len(a)-1
            author_coauthor_edges[author] = author_coauthor_edges.get(author, 0) + max(len(a) - 1, 0)

            if author not in author_to_coauthors:
                author_to_coauthors[author] = set()

            for other in a:
                if other != author:
                    author_to_coauthors[author].add(other)

    metrics = pd.DataFrame({
        "block_key": list(author_n_articles.keys()),
        "n2_n_articles": [author_n_articles[k] for k in author_n_articles.keys()],
        "n2_n_unique_coauthors": [len(author_to_coauthors.get(k, set())) for k in author_n_articles.keys()],
        "n2_n_coauthor_edges": [author_coauthor_edges.get(k, 0) for k in author_n_articles.keys()],
    })

    # Derivado simples (aplicável e interpretável):
    # média de coautores por artigo (aprox) = edges / n_articles
    metrics["n2_mean_coauthors_per_article"] = (
        metrics["n2_n_coauthor_edges"] / metrics["n2_n_articles"].clip(lower=1)
    ).round(3)

    # Sinal ordinal simples (sem “mágica”): baseado em artigos+coautores
    # (thresholds podem ser revisados depois; por ora, bem conservador)
    def n2_tier(row) -> str:
        a = row["n2_n_articles"]
        c = row["n2_n_unique_coauthors"]
        if a >= 5 and c >= 15:
            return "high"
        if a >= 2 and c >= 5:
            return "medium"
        return "low"

    metrics["n2_tier"] = metrics.apply(n2_tier, axis=1)

    _log_line(log_path, f"Metrics shape: {metrics.shape}")

    # -----------------------------
    # Merge back (non-destructive)
    # -----------------------------
    df_out = df.merge(metrics, on="block_key", how="left")

    out_shape = df_out.shape
    _log_line(log_path, f"Output shape: {out_shape}")

    # -----------------------------
    # Save
    # -----------------------------
    df_out.to_csv(output_path, index=False)
    _log_line(log_path, f"Saved: {output_path}")

    manifest = Manifest(
        step_id=step_id,
        run_ts=run_ts,
        input_path=str(input_path),
        output_path=str(output_path),
        input_shape=in_shape,
        output_shape=out_shape,
        notes="N2 coauthorship metrics based on (pmid, block_key). No email/affiliation/orcid used.",
    )

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(asdict(manifest), f, ensure_ascii=False, indent=2)

    _log_line(log_path, f"Manifest: {manifest_path}")
    _log_line(log_path, f"[END] {step_id} | run_id={run_id}")

    print(f"OK: {step_id}")
    print(f"Input:  {input_path} | shape={in_shape}")
    print(f"Output: {output_path} | shape={out_shape}")
    print(f"Log:    {log_path.name}")
    print(f"Manifest:{manifest_path.name}")


if __name__ == "__main__":
    main()
