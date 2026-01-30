# Pipeline Decisions — Lead Generation Funnel (PubMed BR Authors)

## Goal
Build a reproducible, auditable data funnel to generate **qualified leads**:
Brazilian authors — with emphasis on **clinical practitioners** — who publish **low to moderate volumes of scientific articles** and may lack strong, stable ties to academic research institutions.

The funnel prioritizes **traceability, interpretability, and decision robustness** over perfect author identity resolution.
At early stages, **false negatives are acceptable** when they prevent overengineering and reduce downstream risk.

---

## Universe (C0)

**Dataset:** `author_occurrences_unique`  
**Unit of analysis:** author occurrence  
(author × PMID × author_position)  
**Rows:** 430,312  
**Coverage:** 100%

This dataset represents the deduplicated extraction of PubMed XMLs, where technical duplicates across extraction batches were resolved by keeping the most recent extraction per `(pmid, author_position)`.

### Data quality note — affiliation completeness
Before applying any geographic or clinical heuristics, affiliation completeness was explicitly assessed.

- `affiliation_raw = null`: **<<NULL_AFFILIATION_COUNT>>** (<<NULL_AFFILIATION_PCT>>%)
- `affiliation_raw != null`: **<<NON_NULL_AFFILIATION_COUNT>>** (<<NON_NULL_AFFILIATION_PCT>>%)

**Decision:**  
For all downstream heuristics, missing affiliation is treated conservatively as **non-matching** (e.g., non-BR, non-clinical).  
This choice favors precision and auditability, at the cost of potential false negatives.

---

## Stage C1 — Geographic heuristic (explicit Brazil)

**Objective:**  
Reduce international noise early while preserving interpretability.

**Rule:**  
`affiliation_raw` contains `"brasil"` OR `"brazil"` (case-insensitive)

**Implementation:**  
Power Query feature: `feat_br_affiliation_status`  
(Boolean flag derived directly from `affiliation_raw`)

**Logic:**  
- if `affiliation_raw = null` → `FALSE`
- else → substring match

### Counts (author occurrences)
- `TRUE`: **268,978** (62.5%)
- `FALSE`: **161,334** (37.5%)

### Interpretation
The `FALSE` group may include:
- true international affiliations
- Brazilian authors with international or ambiguous affiliation wording
- records with missing affiliation (`null`)

### Decision
C1 is used as a **prioritization slice**, not as a hard exclusion.
All records remain available for later re-inclusion if downstream filters become overly restrictive.

---

## Stage C2 — Author-level aggregation (name-based, non-disambiguated)

**Objective:**  
Move from occurrence-level data to a practical author-centric view, without attempting full identity resolution.

**Key design choice:**  
Authors are clustered **by raw author name string** (`author_name_raw`), accepting the presence of homonyms.

This decision is intentional:
- identity disambiguation is high-cost and high-risk at this stage
- the funnel tolerates false negatives and some false positives
- later manual or business-level validation is expected

**Implementation:**  
Power Query aggregation producing:
- `n_occurrences`: number of author–article occurrences per author name

Resulting table:
- `agr_authors_any_clinical` (intermediate aggregation)

---

## Stage C3 — Clinical signal from affiliation text

**Objective:**  
Identify authors likely to be **clinical practitioners**, rather than exclusively academic researchers.

**Clinical signal definition:**  
Presence of clinical-oriented keywords in `affiliation_raw`, including (non-exhaustive):
- `"hospital"`
- `"clinic"`
- `"medical center"`
- `"medico"`
- `"saude"`

**Implementation:**  
Power Query feature: `feat_clinical_signal` (Boolean)

**Logic:**  
- if `affiliation_raw = null` → `FALSE`
- else → case-insensitive keyword match

### Occurrence-level counts
- `clinical_signal = TRUE`: **117,278**
- `clinical_signal = FALSE`: **313,034**

### Aggregation to author level
An author is flagged as clinical if **any** of their occurrences show a clinical signal.

Derived fields:
- `any_clinical` (Boolean)
- `any_clinical_num` (0/1 numeric helper for aggregation)

Resulting table:
- `agr_authors_any_clinical`

This preserves authors with mixed affiliations (e.g., hospital + university).

---

## Stage C4 — Publication activity metrics

**Objective:**  
Quantify publication volume per author for later prioritization (not filtering yet).

Two complementary metrics were computed:

- `n_occurrences`  
  (number of author–article occurrences; one row per author per article in `author_occurrences_unique`)

- `n_articles`  
  (number of distinct PMIDs per author after removing duplicate author–article pairs)

**Implementation:**  
Author-level aggregation + merge into:
- `agr_authors_summary`

### Consistency check
The comparison between `n_occurrences` (author–article occurrences) and `n_articles` (distinct articles per author) shows that for **>99.9% of authors**, both metrics are identical.

This indicates consistent granularity:
- one author entry per article in practice

Residual cases where `n_occurrences > n_articles` are rare and do not affect lead prioritization decisions.

---

## Current output (ready for BI / business use)

**Table:** `agr_authors_summary`  
**Grain:** author name (string-based cluster)

Key fields available:
- `author_name_raw`
- `n_articles`
- `n_occurrences`
- `any_clinical`
- `any_clinical_num`
- `feat_br_affiliation_status` (via joins if needed)

This table is designed to support:
- ranking
- slicing (clinical vs non-clinical)
- threshold experimentation (publication volume)
- downstream Power BI visual exploration

---

## Known limitations (explicitly accepted)

- No author identity disambiguation (homonyms possible)
- Conservative handling of missing affiliations
- Keyword-based clinical heuristic (language and wording dependent)

These limitations are **documented, intentional, and reversible** in later iterations.

---

## Next planned stages (not executed yet)

- C5: Lead prioritization logic (multi-criteria ranking, no hard thresholds)
- C6: Power BI decision layer (filters, sliders, storytelling views)
- C7: Optional Python refinement (expanded affiliation normalization, if needed)

---

## Stage C5 — Lead prioritization (structural, non-exclusionary)

**Objective:**  
Prepare an author-level decision-ready dataset that supports lead prioritization without applying irreversible filters or hard thresholds.

At this stage, no authors are excluded. Instead, explicit prioritization signals are constructed to enable flexible exploration in the BI layer.

### Inputs
Author-level aggregated table:
- `agr_authors_summary`

Derived signals:
- `any_br_affiliation`: whether the author has at least one occurrence with explicit Brazilian affiliation
- `any_clinical`: whether the author has at least one occurrence with clinical-oriented affiliation keywords
- `n_articles`: number of distinct articles associated with the author

### Author-level aggregation rules
- **Brazil signal (`any_br_affiliation`)**  
  Computed as a MAX aggregation over row-level Brazilian affiliation flags.  
  An author is considered Brazilian if **at least one** of their occurrences explicitly references Brazil.

- **Clinical signal (`any_clinical`)**  
  Computed as a MAX aggregation over row-level clinical keyword matches.  
  This preserves authors with mixed academic and clinical affiliations.

### Lead priority classes
A categorical priority label was assigned to each author based on the combination of geographic and clinical signals:

- `P1_BR_Clinical`: Brazilian authors with at least one clinical affiliation
- `P2_BR_NonClinical`: Brazilian authors without clinical signal
- `P3_NonBR_Clinical`: Non-Brazilian authors with clinical signal
- `P4_Other`: Remaining authors

This classification is **descriptive**, not exclusionary, and is intended solely to guide downstream ranking and exploration.

### Output
Final decision-ready table:
- `mart_leads_authors`

This table represents the canonical author-level data mart for BI consumption and business analysis.

### Decision
All prioritization logic is intentionally implemented as **categorical signals**, not filters.  
Thresholds and final lead selection are deferred to the BI layer to preserve flexibility and traceability.
