"""
99_resolve_block_keys_by_coauthors_n2.py

N2 — resolução conservadora de ambiguidade por coautores.

Objetivo:
- Unir block_keys "vizinhos" (mesmo last_name_norm + first_name_norm) quando
  compartilham >= N coautores em comum (N padrão = 2).

Entradas:
- data/processed/author_occurrences_enriched_n2.csv  (ou enriched.csv, mas aqui usamos o N2 já gerado)

Saídas (não destrutivas):
- data/processed/author_blockkey_cluster_map_n2.csv
- data/processed/author_occurrences_enriched_n2_resolved.csv

Rastreabilidade:
- runs/logs/<run_id>_99_resolve_block_keys_by_coauthors_n2.log
- runs/manifests/<run_id>_99_resolve_block_keys_by_coauthors_n2.json
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import combinations
from pathlib import Path

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
    output_resolved_path: str
    output_map_path: str
    input_shape: tuple[int, int]
    output_shape: tuple[int, int]
    n_clusters: int
    n_block_keys_mapped: int
    params: dict
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


# -----------------------------
# Union-Find (componentes)
# -----------------------------
class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
            return x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for x in list(self.parent.keys()):
            r = self.find(x)
            out.setdefault(r, []).append(x)
        return out


def make_cluster_id(block_keys: list[str]) -> str:
    # ID estável: hash do conjunto ordenado
    s = "|".join(sorted(block_keys))
    return "clu_" + hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def main() -> None:
    _ensure_dirs()

    step_id = "99_resolve_block_keys_by_coauthors_n2"
    run_ts = _now_ts()
    run_id = f"{run_ts}_{_short_hash(step_id + run_ts)}"

    input_path = DATA_PROCESSED / "author_occurrences_enriched_n2.csv"
    output_map_path = DATA_PROCESSED / "author_blockkey_cluster_map_n2.csv"
    output_resolved_path = DATA_PROCESSED / "author_occurrences_enriched_n2_resolved.csv"

    log_path = RUNS_LOGS / f"{run_id}_{step_id}.log"
    manifest_path = RUNS_MANIFESTS / f"{run_id}_{step_id}.json"

    # Parâmetros (ajustáveis depois; por ora fixo no seu critério)
    MIN_SHARED_COAUTHORS = 2
    MAX_BLOCKKEYS_PER_NAME_GROUP = 60  # proteção contra explosão combinatória

    params = {
        "min_shared_coauthors": MIN_SHARED_COAUTHORS,
        "candidate_group_by": ["last_name_norm", "first_name_norm"],
        "max_blockkeys_per_name_group": MAX_BLOCKKEYS_PER_NAME_GROUP,
    }

    if not input_path.exists():
        raise FileNotFoundError(f"Input não encontrado: {input_path}")

    _log_line(log_path, f"[START] {step_id} | run_id={run_id}")
    _log_line(log_path, f"Input: {input_path}")

    df = pd.read_csv(input_path, low_memory=False)

    required = ["pmid", "block_key", "last_name_norm", "first_name_norm", "name_parse_ok"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes: {missing}")

    in_shape = df.shape
    _log_line(log_path, f"Input shape: {in_shape}")

    # Normalização mínima
    df["pmid"] = df["pmid"].astype(str)
    df["block_key"] = df["block_key"].astype(str)

    # Trabalhar só onde parse ok e nome suficiente para criar candidatos
    df_ok = df[df["name_parse_ok"] == True].copy()  # noqa: E712
    df_ok = df_ok.dropna(subset=["last_name_norm", "first_name_norm", "block_key", "pmid"])
    _log_line(log_path, f"Working subset (name_parse_ok & non-null keys): {df_ok.shape}")

    # -----------------------------
    # 1) Construir conjuntos de coautores por block_key
    # -----------------------------
    pmid_authors = (
        df_ok[["pmid", "block_key"]]
        .drop_duplicates()
        .groupby("pmid")["block_key"]
        .apply(list)
    )

    coauthors: dict[str, set[str]] = {}
    for pmid, authors in pmid_authors.items():
        a = list(dict.fromkeys(authors))
        if len(a) < 2:
            continue
        for author in a:
            coauthors.setdefault(author, set())
            for other in a:
                if other != author:
                    coauthors[author].add(other)

    _log_line(log_path, f"Coauthor sets built for block_keys: {len(coauthors)}")

    # -----------------------------
    # 2) Gerar pares candidatos por (last_name_norm, first_name_norm)
    # -----------------------------
    name_groups = (
        df_ok[["block_key", "last_name_norm", "first_name_norm"]]
        .drop_duplicates()
        .groupby(["last_name_norm", "first_name_norm"])["block_key"]
        .apply(list)
    )

    uf = UnionFind()
    edges = 0
    skipped_groups = 0

    for (ln, fn), bks in name_groups.items(): # type: ignore
        uniq = sorted(set(bks))
        if len(uniq) <= 1:
            continue

        # proteção (grupos enormes geram muitas combinações)
        if len(uniq) > MAX_BLOCKKEYS_PER_NAME_GROUP:
            skipped_groups += 1
            _log_line(log_path, f"[SKIP] huge name group ({ln}, {fn}) size={len(uniq)}")
            continue

        # registrar nós no UF
        for bk in uniq:
            uf.find(bk)

        # pares
        for a, b in combinations(uniq, 2):
            sa = coauthors.get(a, set())
            sb = coauthors.get(b, set())
            if not sa or not sb:
                continue
            shared = len(sa.intersection(sb))
            if shared >= MIN_SHARED_COAUTHORS:
                uf.union(a, b)
                edges += 1

    _log_line(log_path, f"Edges created (shared_coauthors >= {MIN_SHARED_COAUTHORS}): {edges}")
    _log_line(log_path, f"Skipped huge name groups: {skipped_groups}")

    # -----------------------------
    # 3) Construir clusters e map
    # -----------------------------
    groups = uf.groups()
    # criar cluster_id estável por componente
    cluster_rows = []
    for root, members in groups.items():
        cid = make_cluster_id(members)
        for bk in members:
            cluster_rows.append((bk, cid, len(members)))

    map_df = pd.DataFrame(cluster_rows, columns=["block_key", "author_cluster_id", "author_cluster_size"])

    # Para block_keys que não entraram em nenhum grupo (não ambíguos), também mapear (cluster unitário)
    # (opção conservadora: mapear todos)
    all_bk = sorted(set(df_ok["block_key"].dropna().astype(str).tolist()))
    mapped = set(map_df["block_key"].tolist())
    missing_bk = [bk for bk in all_bk if bk not in mapped]

    if missing_bk:
        extra = []
        for bk in missing_bk:
            cid = make_cluster_id([bk])
            extra.append((bk, cid, 1))
        map_df = pd.concat([map_df, pd.DataFrame(extra, columns=map_df.columns)], ignore_index=True)

    map_df = map_df.drop_duplicates(subset=["block_key"])
    _log_line(log_path, f"Total block_keys mapped: {map_df.shape[0]}")
    _log_line(log_path, f"Total clusters: {map_df['author_cluster_id'].nunique()}")

    # -----------------------------
    # 4) Merge back (não destrutivo) + salvar
    # -----------------------------
    df_out = df.merge(map_df, on="block_key", how="left")

    out_shape = df_out.shape
    df_out.to_csv(output_resolved_path, index=False)
    map_df.to_csv(output_map_path, index=False)

    manifest = Manifest(
        step_id=step_id,
        run_id=run_id,
        run_ts=run_ts,
        input_path=str(input_path),
        output_resolved_path=str(output_resolved_path),
        output_map_path=str(output_map_path),
        input_shape=in_shape,
        output_shape=out_shape,
        n_clusters=int(map_df["author_cluster_id"].nunique()),
        n_block_keys_mapped=int(map_df.shape[0]),
        params=params,
        notes="Conservative coauthor-based linkage inside (last_name_norm, first_name_norm) groups; merge if shared coauthors >= threshold.",
    )

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(asdict(manifest), f, ensure_ascii=False, indent=2)

    _log_line(log_path, f"Saved resolved: {output_resolved_path}")
    _log_line(log_path, f"Saved map:      {output_map_path}")
    _log_line(log_path, f"Manifest:       {manifest_path}")
    _log_line(log_path, f"[END] {step_id} | run_id={run_id}")

    print(f"OK: {step_id}")
    print(f"Input:   {input_path} | shape={in_shape}")
    print(f"Output1: {output_resolved_path} | shape={out_shape}")
    print(f"Output2: {output_map_path} | rows={map_df.shape[0]}")
    print(f"Log:     {log_path.name}")
    print(f"Manifest:{manifest_path.name}")


if __name__ == "__main__":
    main()
