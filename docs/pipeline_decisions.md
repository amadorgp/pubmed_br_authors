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

Clinical Heuristic — Conservative Design Choice

The definition of “clinical author” adopted in this pipeline is intentionally conservative. An author is classified as clinical only when at least one of their affiliations explicitly contains healthcare-related keywords (e.g., hospital, clinic, medical center, médico, saúde), evaluated at the occurrence level and aggregated to the author level using an ANY rule.

This design prioritizes precision over recall. Authors affiliated with laboratories, research institutes, or academic departments without explicit clinical keywords are deliberately excluded, even though some of them may be involved in applied or translational research. This choice reflects the project’s primary objective: building a practical lead generation tool, where false positives (non-clinical profiles incorrectly classified as clinical) are considered more costly than false negatives.

More permissive heuristics — such as including laboratories or institutes — were evaluated conceptually but rejected for this version of the pipeline due to increased semantic ambiguity, higher risk of false positives, and significant scope expansion. Such extensions are considered out of scope for the current version and are explicitly reserved for future iterations under a separate, versioned clinical definition.

## Stage N1 — Author Name Normalization (Non-Identitary)

### Objective
Introduce a conservative, non-identitary normalization layer for author names,
enabling exploratory grouping and downstream heuristics without attempting
author identity resolution.

This stage is explicitly designed to:
- preserve the original author name as published
- avoid premature merging of homonyms
- support exploratory analysis and prioritization logic

---

### Input
Dataset:
- `author_occurrences_enriched.csv`

Key column:
- `author_name_raw` (as extracted from PubMed)

---

### Normalization Strategy (Conservative by Design)

The following transformations are applied:

1. **ASCII normalization**
   - Removal of diacritics (e.g., `José` → `Jose`)
   - No other structural modification

2. **Text standardization**
   - Lowercasing
   - Whitespace normalization
   - Controlled removal of punctuation
   - Hyphens normalized to spaces

3. **PubMed-style name parsing**
   Expected format:

Parsed components:
- `last_name_norm`
- `first_name_norm`
- `initials_norm` (derived from first letters of given names)

4. **Block key generation (neighborhood only)**

This key is used **only for neighborhood grouping**, not for identity.

---

### Explicit Non-Goals (Critical Design Constraints)

This stage deliberately does **not**:
- assign a unique author identifier
- merge records across publications
- resolve homonyms
- enforce ORCID presence
- override conflicting affiliations

All such operations are deferred to later stages (e.g., N2), if needed.

---

### Quality Metrics (Observed)

From 430,312 author occurrences:

- Successful name parsing: **99.70%**
- Parsing failures: **0.30%** (1,280 rows)
- Non-null block keys: **99.70%**
- Distinct block keys: **214,832**

The most frequent block keys correspond to well-known international homonyms
(e.g., `jones_l`, `lee_i`), confirming that the block key exposes name ambiguity
rather than obscuring it.

---

### Rationale for Acceptance

This stage was accepted as stable because:
- parsing success exceeds typical bibliographic benchmarks
- ambiguity is made explicit, not hidden
- original data is fully preserved
- the transformation is reversible and non-destructive

The resulting columns are suitable for exploratory analysis, prioritization,
and visualization, while remaining compatible with more advanced disambiguation
strategies in future stages.

---

### Outputs (Added Columns)

- `author_name_ascii`
- `author_name_clean`
- `last_name_norm`
- `first_name_norm`
- `initials_norm`
- `block_key`
- `name_parse_ok`

These columns are considered **stable artifacts** of Stage N1.
### Stage N2 (Revised) — Coauthor-based identity resolution (conservative, auditável)

Objective
Resolve residual author name ambiguity exposed in Stage N1 by assigning a practical, auditável author identity, using coauthorship structure as the sole resolution signal, while preserving reversibility and traceability.

This stage represents a controlled transition from exploratory grouping to a usable author-level identity required for downstream lead generation.

Key Design Decision (Explicit)

At this stage, a global analytical author identifier is introduced:

author_cluster_id

This identifier is:

derived deterministically

conservative by construction

auditável and reversible

sufficient for business and BI consumption, but not claimed as perfect author disambiguation

False negatives are explicitly accepted. False positives are treated as the primary risk to avoid.

Inputs

Dataset:

author_occurrences_enriched_n2_resolved.csv

Key columns:

pmid

block_key

last_name_norm

first_name_norm

coauthor block keys (derived from shared PMIDs)

Resolution Strategy (Coauthorship-Only, Name-Constrained)

Candidate author identities are evaluated only within name neighborhoods, defined by:

same last_name_norm

same first_name_norm

No cross-name matching is allowed.

Within each neighborhood, two block_key values are considered to represent the same author if:

they share ≥ 2 distinct coauthors, across any number of PMIDs

Coauthors are identified exclusively by their own block_key values.

This rule is intentionally:

simple

deterministic

transparent

conservative

Group Construction Logic

Candidate matches form an undirected graph within each name neighborhood.

Author identities are constructed via transitive closure:

if A matches B, and B matches C → A, B, C belong to the same author cluster

if no rule is satisfied → the block key remains a singleton cluster

Each resulting connected component is assigned a stable identifier:

author_cluster_id

Outputs

Two explicit artifacts are generated:

Author–Block Mapping

author_blockkey_cluster_map_n2.csv

Maps each block_key to a single author_cluster_id

Fully auditável and reversible

Resolved Author Occurrences

author_occurrences_enriched_n2_resolved.csv

Original occurrence-level data, augmented with:

author_cluster_id

author_cluster_size

No original data is removed or overwritten.

Observed Impact (Sanity Check)

From 430,312 author occurrences:

~90% of block keys remain singletons

~10% are merged via conservative coauthor evidence

Large clusters are rare and interpretable

This confirms that the resolution strategy reduces fragmentation without aggressive merging.

Explicit Non-Goals (Reaffirmed)

This stage deliberately does not:

claim perfect author identity resolution

resolve global homonyms

use email, affiliation, ORCID, or text similarity

apply probabilistic or ML-based disambiguation

All such refinements remain optional future extensions.

(2) Adicionar nova seção após “Current output (ready for BI / business use)”
Final Consumption Mart — Author-Level (Auditável)

Table: mart_leads_authors
Grain: one row per author_cluster_id
Purpose: canonical author-level dataset for BI exploration and lead generation.

Construction Logic

The mart is derived from author_occurrences_enriched_n2_resolved.csv by aggregating on:

author_cluster_id

Each row represents a practical author identity, suitable for ranking, filtering, and business decision-making.

Key Fields

author_cluster_id — analytical author identifier (primary key)

canonical_author_name — most frequent raw author name (display / audit)

n_articles — number of distinct PMIDs

n_occurrences — total author–article occurrences

author_cluster_size — number of block keys merged

any_clinical / any_br_affiliation (if available)

optional enrichment fields (e.g., email example, state example)

Auditability and Traceability

The mart is fully traceable:

author_cluster_id
→ block_key
→ author_name_raw
→ pmid
→ original PubMed XML record

No information loss occurs. The mart is a summary layer, not a destructive transformation.

Decision

mart_leads_authors is adopted as the single source of truth for:

Power BI modeling

lead prioritization

business-facing analysis

All filtering and threshold decisions are intentionally deferred to the BI layer to preserve flexibility and interpretability.

## Final State and Scope Freeze

This document records the final, frozen state of the decision-making process for the PubMed BR Authors pipeline.

At this stage, the pipeline is considered **complete, stable, and fit for purpose** with respect to its original objective: generating a qualified, auditable, and operationally usable list of Brazilian clinical authors for outreach and lead generation.

### What Was Implemented

The final pipeline includes:

- A reproducible ingestion and normalization flow for PubMed data (2020–2024).
- Author-level identity resolution using conservative block-key logic and co-author evidence.
- Explicit acceptance of false negatives to preserve interpretability and robustness.
- A conservative clinical heuristic based on explicit healthcare-related affiliations.
- Lead prioritization (`P1–P4`) aligned with business relevance rather than academic completeness.
- A final, versioned mart of authors suitable for downstream consumption.
- Exported lead artifacts with full traceability (logs, manifests, and schema documentation).

### Deliberate Exclusions

The following were explicitly considered and **intentionally excluded** from this version:

- Aggressive author identity resolution (e.g., probabilistic or ML-based disambiguation).
- Automated validation of email ownership or correspondence authorship.
- Inclusion of laboratories, institutes, or academic departments without explicit clinical signals.
- External enrichment via web scraping or third-party services.
- Campaign-specific or outreach-specific decision rules (e.g., filtering by publication count).

These exclusions reflect a conscious trade-off favoring **precision, auditability, and operational reliability** over maximal recall or automation.

### Versioning and Future Extensions

Any extension of scope — such as relaxed clinical heuristics, email validation strategies, or campaign-level prioritization — is considered **out**
