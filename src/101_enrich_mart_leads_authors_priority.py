from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


# ============================================================
# Clinical criteria (MUST match docs/pipeline_decisions.md C3)
# - if affiliation_raw is null -> FALSE
# - else case-insensitive keyword match
# - author-level: ANY occurrence => any_clinical = TRUE
# ============================================================

CLINICAL_KEYWORDS = [
    "hospital",
    "clinic",
    "medical center",
    "medico",
    "saude",
]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
RUNS_DIR = PROJECT_ROOT / "runs"
RUNS_LOGS = RUNS_DIR / "logs"
RUNS_MANIFESTS = RUNS_DIR / "manifests"


@dataclass
class Manifest:
    step_id: str
    run_id: str
    run_ts: str
    input_occurrences: str
    input_mart: str
    output_mart: str
    input_shapes: dict
    output_shape: tuple[int, int]
    rules: dict


def _ensure_dirs() -> None:
    RUNS_LOGS.mkdir(parents=True, exist_ok=True)
    RUNS_MANIFESTS.mkdir(parents=True, exist_ok=True)


def _now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    # docs rule: null -> FALSE
    if not isinstance(text, str) or not text:
        return False
    t = text.casefold()
    return any(k.casefold() in t for k in keywords)


def _safe_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s.fillna(False)
    return s.fillna(False).astype(bool)


def _priority(br: bool, clin: bool) -> str:
    # P1–P4 as defined in project discussions
    if br and clin:
        return "P1_BR_Clinical"
    if br and not clin:
        return "P2_BR_NonClinical"
    if (not br) and clin:
        return "P3_NonBR_Clinical"
    return "P4_Other"


def main() -> None:
    _ensure_dirs()

    step_id = "101_enrich_mart_leads_authors_priority"
    run_ts = _now_ts()
    run_id = f"{run_ts}_{_short_hash(step_id + run_ts)}"

    occ_path = DATA_PROCESSED / "author_occurrences_enriched_n2_resolved.csv"
    mart_path = DATA_PROCESSED / "mart_leads_authors.csv"
    out_path = DATA_PROCESSED / "mart_leads_authors_v2.csv"

    log_path = RUNS_LOGS / f"{run_id}_{step_id}.log"
    manifest_path = RUNS_MANIFESTS / f"{run_id}_{step_id}.json"

    if not occ_path.exists():
        raise FileNotFoundError(f"Missing input: {occ_path}")
    if not mart_path.exists():
        raise FileNotFoundError(f"Missing input: {mart_path}")

    occ = pd.read_csv(occ_path, low_memory=False)
    mart = pd.read_csv(mart_path, low_memory=False)

    # Schema guards
    for c in ["author_cluster_id", "affiliation_raw"]:
        if c not in occ.columns:
            raise ValueError(f"Occurrences missing required column: {c}")
    if "author_cluster_id" not in mart.columns:
        raise ValueError("Mart missing required column: author_cluster_id")
    if "any_br_affiliation" not in mart.columns:
        raise ValueError(
            "Mart missing 'any_br_affiliation'. "
            "Stop: we are keeping BR criterion consistent with existing mart."
        )

    occ["author_cluster_id"] = occ["author_cluster_id"].astype(str)
    mart["author_cluster_id"] = mart["author_cluster_id"].astype(str)

    # ---- C3: occurrence-level clinical signal (docs exact rule)
    occ["_clinical_signal"] = occ["affiliation_raw"].apply(lambda x: _contains_any(x, CLINICAL_KEYWORDS))

    # ---- author-level ANY aggregation
    clin = (
        occ.groupby("author_cluster_id", as_index=False)
        .agg(any_clinical=("_clinical_signal", "max"))
    )
    clin["any_clinical"] = _safe_bool(clin["any_clinical"])
    clin["any_clinical_num"] = clin["any_clinical"].astype(int)

    # ---- merge into mart (no column collisions)
    out = mart.merge(clin, on="author_cluster_id", how="left")
    out["any_br_affiliation"] = _safe_bool(out["any_br_affiliation"])
    out["any_clinical"] = _safe_bool(out["any_clinical"])
    out["any_clinical_num"] = out["any_clinical_num"].fillna(0).astype(int)

    # ---- priority
    out["lead_priority"] = [
        _priority(br, clin) for br, clin in zip(out["any_br_affiliation"], out["any_clinical"])
    ]

    # Sanity: categories
    expected = sorted(["P1_BR_Clinical", "P2_BR_NonClinical", "P3_NonBR_Clinical", "P4_Other"])
    got = sorted(out["lead_priority"].unique().tolist())
    if got != expected:
        raise ValueError(f"Unexpected lead_priority categories: {got}")

    out.to_csv(out_path, index=False, encoding="utf-8")

    counts = out["lead_priority"].value_counts()

    # log
    log_path.write_text(
        "\n".join([
            f"[START] {step_id} | run_id={run_id}",
            f"Input occurrences: {occ_path} | shape={occ.shape}",
            f"Input mart:        {mart_path} | shape={mart.shape}",
            f"Output mart:       {out_path} | shape={out.shape}",
            "lead_priority_counts:",
            counts.to_string(),
            f"[END] {step_id} | run_id={run_id}",
        ]) + "\n",
        encoding="utf-8",
    )

    manifest = Manifest(
        step_id=step_id,
        run_id=run_id,
        run_ts=run_ts,
        input_occurrences=str(occ_path),
        input_mart=str(mart_path),
        output_mart=str(out_path),
        input_shapes={"occurrences": tuple(occ.shape), "mart": tuple(mart.shape)},
        output_shape=tuple(out.shape), # type: ignore
        rules={
            "clinical_keywords": CLINICAL_KEYWORDS,
            "clinical_rule": "affiliation_raw null => FALSE; else case-insensitive substring match; author ANY => TRUE",
            "priority_mapping": {
                "P1_BR_Clinical": "any_br_affiliation=True AND any_clinical=True",
                "P2_BR_NonClinical": "any_br_affiliation=True AND any_clinical=False",
                "P3_NonBR_Clinical": "any_br_affiliation=False AND any_clinical=True",
                "P4_Other": "else",
            },
        },
    )
    manifest_path.write_text(json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OK: {step_id}")
    print(f"Output: {out_path} | shape={out.shape}")
    print("lead_priority_counts:")
    print(counts.to_string())
    print(f"Log: {log_path.name}")
    print(f"Manifest: {manifest_path.name}")


if __name__ == "__main__":
    main()
