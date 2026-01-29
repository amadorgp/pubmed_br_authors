"""
04_parse_xml_to_csv_by_year.py

Objetivo:
- Ler XMLs brutos baixados via EFetch (por ano)
- Extrair:
  (A) artigos: 1 linha por PMID (inclui ABSTRACT)
  (B) autor-ocorrência: 1 linha por autor em cada PMID (inclui afiliação e ORCID quando houver)
- Escrever CSVs por ano, de forma incremental (append), com checkpoint por arquivo XML.
- Gerar manifesto de execução.

Observações:
- Não faz deduplicação de autores (homônimos ficam para fases posteriores).
- Não faz inferências agressivas (mantém strings brutas).
"""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, TextIO

from dotenv import load_dotenv
from tqdm import tqdm

# lxml pode não ter stubs completos para type checking do PyLance
from lxml import etree  # type: ignore


# ---------------------------------------------------------------------
# Paths do projeto
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.env"

EFETCH_ROOT = PROJECT_ROOT / "data" / "raw" / "efetch_by_year"
PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed"

CHECKPOINTS = PROJECT_ROOT / "runs" / "checkpoints"
MANIFESTS = PROJECT_ROOT / "runs" / "manifests"


@dataclass
class ParseConfig:
    strategy_id: str
    year_start: int
    year_end: int
    # Se quiser limitar artigos por ano para testes, defina um int; caso contrário, None.
    max_articles_per_year: int | None = None


# ---------------------------------------------------------------------
# Utilidades de limpeza leve (não agressiva)
# ---------------------------------------------------------------------

_ws_re = re.compile(r"\s+")

def clean_text(s: str | None) -> str:
    if not s:
        return ""
    return _ws_re.sub(" ", s).strip()


def join_nonempty(parts: Iterable[str], sep: str = " | ") -> str:
    vals = [clean_text(p) for p in parts if clean_text(p)]
    return sep.join(vals)


# ---------------------------------------------------------------------
# Extração de campos do PubMed XML (ArticleSet)
# ---------------------------------------------------------------------

def get_text(node: etree._Element | None) -> str:
    if node is None:
        return ""
    return clean_text("".join(node.itertext()))


def first(node: etree._Element, xpath: str) -> etree._Element | None:
    found = node.xpath(xpath)
    return found[0] if found else None


def many(node: etree._Element, xpath: str) -> list[etree._Element]:
    return list(node.xpath(xpath))


def extract_pub_year(pubmed_article: etree._Element) -> str:
    # Tenta PubDate Year, depois MedlineDate (ex: "2020 Jan-Feb")
    year_node = first(pubmed_article, ".//Article//Journal//JournalIssue//PubDate//Year")
    if year_node is not None:
        return get_text(year_node)

    medline_date = first(pubmed_article, ".//Article//Journal//JournalIssue//PubDate//MedlineDate")
    if medline_date is not None:
        md = get_text(medline_date)
        # pega o primeiro bloco de 4 dígitos
        m = re.search(r"(19|20)\d{2}", md)
        if m:
            return m.group(0)

    # fallback: DateCompleted Year
    dc = first(pubmed_article, ".//DateCompleted//Year")
    if dc is not None:
        return get_text(dc)

    return ""


def extract_doi(pubmed_article: etree._Element) -> str:
    # DOI costuma vir em ArticleIdList/ArticleId[@IdType="doi"]
    doi_node = first(pubmed_article, './/PubmedData//ArticleIdList//ArticleId[@IdType="doi"]')
    return get_text(doi_node)


def extract_publication_types(pubmed_article: etree._Element) -> str:
    pts = [get_text(n) for n in many(pubmed_article, ".//Article//PublicationTypeList//PublicationType")]
    return join_nonempty(pts, sep="; ")


def extract_abstract(pubmed_article: etree._Element) -> str:
    """
    Abstract pode ter múltiplos AbstractText, às vezes com Label/NlmCategory.
    Vamos concatenar mantendo uma marcação simples.
    """
    abstract_nodes = many(pubmed_article, ".//Article//Abstract//AbstractText")
    if not abstract_nodes:
        return ""

    chunks: list[str] = []
    for n in abstract_nodes:
        label = n.get("Label") or n.get("NlmCategory") or ""
        text = get_text(n)
        if not text:
            continue
        if label:
            chunks.append(f"{label}: {text}")
        else:
            chunks.append(text)

    return clean_text("\n".join(chunks))


def extract_journal(pubmed_article: etree._Element) -> str:
    j = first(pubmed_article, ".//Article//Journal//Title")
    if j is not None:
        return get_text(j)
    iso = first(pubmed_article, ".//Article//Journal//ISOAbbreviation")
    return get_text(iso)


def extract_title(pubmed_article: etree._Element) -> str:
    t = first(pubmed_article, ".//Article//ArticleTitle")
    return get_text(t)


def extract_pmid(pubmed_article: etree._Element) -> str:
    pmid_node = first(pubmed_article, ".//MedlineCitation//PMID")
    return get_text(pmid_node)


def extract_authors(pubmed_article: etree._Element) -> list[dict]:
    """
    Retorna lista de autores (como dict), mantendo dados brutos.
    Papel: first/middle/last baseado na posição.
    Afiliação: mantém Affiliation raw (pode haver múltiplas por autor).
    ORCID: quando houver Identifier[@Source="ORCID"].
    """
    authors = many(pubmed_article, ".//Article//AuthorList//Author")
    out: list[dict] = []

    # conta autores "válidos" (às vezes há Author com CollectiveName apenas)
    n = len(authors)

    for idx, a in enumerate(authors, start=1):
        # Nome: preferir LastName + ForeName; fallback para CollectiveName
        last = get_text(first(a, "./LastName"))
        fore = get_text(first(a, "./ForeName"))
        initials = get_text(first(a, "./Initials"))
        suffix = get_text(first(a, "./Suffix"))
        collective = get_text(first(a, "./CollectiveName"))

        if collective:
            name_raw = collective
        else:
            parts = []
            if last:
                parts.append(last)
            if fore:
                parts.append(fore)
            elif initials:
                parts.append(initials)
            if suffix:
                parts.append(suffix)
            name_raw = ", ".join(parts) if parts else ""

        # ORCID
        orcid_node = first(a, './Identifier[@Source="ORCID"]')
        orcid = get_text(orcid_node)

        # Afiliação(ões)
        affs = [get_text(x) for x in many(a, ".//AffiliationInfo//Affiliation")]
        affiliation_raw = join_nonempty(affs, sep=" || ")

        # Role
        if idx == 1:
            role = "first"
        elif idx == n:
            role = "last"
        else:
            role = "middle"

        out.append(
            {
                "author_position": idx,
                "author_role": role,
                "author_name_raw": name_raw,
                "orcid": orcid,
                "affiliation_raw": affiliation_raw,
            }
        )

    return out


# ---------------------------------------------------------------------
# Checkpoint / escrita incremental
# ---------------------------------------------------------------------

def checkpoint_path(strategy_id: str, year: int) -> Path:
    return CHECKPOINTS / f"{strategy_id}_parse_{year}.json"


def load_checkpoint(strategy_id: str, year: int) -> int:
    p = checkpoint_path(strategy_id, year)
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        return int(data.get("xml_file_index", 0))
    return 0


def save_checkpoint(strategy_id: str, year: int, xml_file_index: int) -> None:
    p = checkpoint_path(strategy_id, year)
    p.write_text(json.dumps({"xml_file_index": xml_file_index}, indent=2), encoding="utf-8")


def open_csv_writer(path: Path, fieldnames: list[str]) -> tuple[csv.DictWriter, TextIO]:
    """
    Abre CSV em modo append. Se arquivo não existir, escreve header.
    Retorna writer e handle do arquivo (para fechar).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    f = open(path, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    if not file_exists:
        writer.writeheader()
    return writer, f


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    load_dotenv(CONFIG_PATH)

    cfg = ParseConfig(
        strategy_id="A1_v2_2020_2024_no_trials",
        year_start=2020,
        year_end=2024,
        max_articles_per_year=None,  # mude para um int se quiser testar rápido
    )

    PROCESSED_ROOT.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{cfg.strategy_id}_PARSE_XML_TO_CSV"

    # Definição de colunas (fixas)
    article_fields = [
        "pmid",
        "pub_year",
        "journal",
        "article_title",
        "doi",
        "publication_types",
        "abstract",
        "xml_source_file",
        "extraction_date",
        "strategy_id",
        "source",
    ]

    author_fields = [
        "pmid",
        "pub_year",
        "journal",
        "article_title",
        "doi",
        "author_position",
        "author_role",
        "author_name_raw",
        "orcid",
        "affiliation_raw",
        "xml_source_file",
        "extraction_date",
        "strategy_id",
        "source",
    ]

    extraction_date = datetime.now().date().isoformat()

    manifest_summary: dict[int, dict] = {}

    for year in range(cfg.year_start, cfg.year_end + 1):
        year_dir = EFETCH_ROOT / str(year)
        if not year_dir.exists():
            print(f"WARNING: No EFetch directory for year {year}. Skipping.")
            continue

        xml_files = sorted(year_dir.glob("*.xml"))
        if not xml_files:
            print(f"WARNING: No XML files found for year {year}. Skipping.")
            continue

        start_index = load_checkpoint(cfg.strategy_id, year)

        out_articles = PROCESSED_ROOT / f"articles_{year}.csv"
        out_authors = PROCESSED_ROOT / f"author_occurrences_{year}.csv"

        # Inicializa handles para satisfazer o analisador estático (PyLance)
        article_handle: TextIO | None = None
        author_handle: TextIO | None = None

        article_writer, article_handle = open_csv_writer(out_articles, article_fields)
        author_writer, author_handle = open_csv_writer(out_authors, author_fields)

        total_articles = 0
        total_author_rows = 0
        skipped_no_pmid = 0

        pbar = tqdm(
            total=len(xml_files),
            initial=start_index,
            desc=f"Parse {year}",
            unit="xml"
        )

        try:
            for i in range(start_index, len(xml_files)):
                xml_path = xml_files[i]

                # Parse do XML inteiro (batch de ~100 artigos)
                # Observação: se algum dia isso ficar pesado, migramos para iterparse.
                try:
                    tree = etree.parse(str(xml_path))
                except Exception as exc:
                    print(f"WARNING: Failed to parse XML {xml_path.name}: {exc}")
                    # checkpoint avança para não ficar preso
                    save_checkpoint(cfg.strategy_id, year, i + 1)
                    pbar.update(1)
                    continue

                articles = tree.xpath("//PubmedArticle")
                for a in articles:
                    pmid = extract_pmid(a)
                    if not pmid:
                        skipped_no_pmid += 1
                        continue

                    pub_year = extract_pub_year(a)
                    title = extract_title(a)
                    journal = extract_journal(a)
                    doi = extract_doi(a)
                    pub_types = extract_publication_types(a)
                    abstract = extract_abstract(a)

                    # Linha de ARTIGO (1 por PMID)
                    article_writer.writerow(
                        {
                            "pmid": pmid,
                            "pub_year": pub_year,
                            "journal": journal,
                            "article_title": title,
                            "doi": doi,
                            "publication_types": pub_types,
                            "abstract": abstract,
                            "xml_source_file": xml_path.name,
                            "extraction_date": extraction_date,
                            "strategy_id": cfg.strategy_id,
                            "source": "PubMed",
                        }
                    )
                    total_articles += 1

                    # Linhas de AUTOR-OCORRÊNCIA (N por artigo)
                    author_rows = extract_authors(a)
                    for r in author_rows:
                        author_writer.writerow(
                            {
                                "pmid": pmid,
                                "pub_year": pub_year,
                                "journal": journal,
                                "article_title": title,
                                "doi": doi,
                                "author_position": r["author_position"],
                                "author_role": r["author_role"],
                                "author_name_raw": r["author_name_raw"],
                                "orcid": r["orcid"],
                                "affiliation_raw": r["affiliation_raw"],
                                "xml_source_file": xml_path.name,
                                "extraction_date": extraction_date,
                                "strategy_id": cfg.strategy_id,
                                "source": "PubMed",
                            }
                        )
                        total_author_rows += 1

                    if cfg.max_articles_per_year is not None and total_articles >= cfg.max_articles_per_year:
                        break

                # Avança checkpoint por arquivo XML processado
                save_checkpoint(cfg.strategy_id, year, i + 1)
                pbar.update(1)

                if cfg.max_articles_per_year is not None and total_articles >= cfg.max_articles_per_year:
                    break

        finally:
            pbar.close()
            if article_handle is not None:
                article_handle.close()
            if author_handle is not None:
                author_handle.close()

        manifest_summary[year] = {
            "xml_files_total": len(xml_files),
            "xml_files_started_at_index": start_index,
            "xml_files_processed_to_index": load_checkpoint(cfg.strategy_id, year),
            "articles_rows_written": total_articles,
            "author_occurrence_rows_written": total_author_rows,
            "skipped_no_pmid": skipped_no_pmid,
            "articles_csv": str(out_articles),
            "author_occurrences_csv": str(out_authors),
        }

        print(
            f"\nYear {year} done. articles={total_articles}, author_rows={total_author_rows}, "
            f"skipped_no_pmid={skipped_no_pmid}"
        )

    manifest = {
        "run_id": run_id,
        "stage": "parse_xml_to_csv_by_year",
        "strategy_id": cfg.strategy_id,
        "includes_abstract": True,
        "output": {
            "processed_root": str(PROCESSED_ROOT),
            "pattern_articles": "articles_<year>.csv",
            "pattern_author_occurrences": "author_occurrences_<year>.csv",
        },
        "summary_by_year": manifest_summary,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "source": "PubMed",
    }

    (MANIFESTS / f"{run_id}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("\nPARSE XML TO CSV completed.")
    print("STATUS: OK")


if __name__ == "__main__":
    main()
