# Data Dictionary

## Dataset: `articles_all`

| column_name | data_type | column_role | nullable | nunique | null_count | null_pct | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pmid | int64 | primary_identifier | False | 49734 | 0 | 0.0 |  |
| pub_year | int64 | temporal | False | 7 | 0 | 0.0 |  |
| journal | str | categorical | False | 3711 | 0 | 0.0 |  |
| article_title | str | free_text | False | 49632 | 0 | 0.0 |  |
| doi | str | identifier_optional | True | 49495 | 226 | 0.00452045204520452 |  |
| publication_types | str | categorical | False | 583 | 0 | 0.0 |  |
| abstract | str | free_text | True | 44735 | 4983 | 0.09966996699669967 |  |
| xml_source_file | str | governance | False | 100 | 0 | 0.0 |  |
| extraction_date | str | governance | False | 1 | 0 | 0.0 |  |
| strategy_id | str | governance | False | 1 | 0 | 0.0 |  |
| source | str | governance | False | 1 | 0 | 0.0 |  |

## Dataset: `articles_unique`

| column_name | data_type | column_role | nullable | nunique | null_count | null_pct | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pmid | int64 | primary_identifier | False | 49734 | 0 | 0.0 |  |
| pub_year | int64 | temporal | False | 7 | 0 | 0.0 |  |
| journal | str | categorical | False | 3711 | 0 | 0.0 |  |
| article_title | str | free_text | False | 49632 | 0 | 0.0 |  |
| doi | str | identifier_optional | True | 49495 | 226 | 0.004544175011058833 |  |
| publication_types | str | categorical | False | 583 | 0 | 0.0 |  |
| abstract | str | free_text | True | 44735 | 4981 | 0.10015281296497366 |  |
| xml_source_file | str | governance | False | 100 | 0 | 0.0 |  |
| extraction_date | str | governance | False | 1 | 0 | 0.0 |  |
| strategy_id | str | governance | False | 1 | 0 | 0.0 |  |
| source | str | governance | False | 1 | 0 | 0.0 |  |

## Dataset: `author_occurrences_all`

| column_name | data_type | column_role | nullable | nunique | null_count | null_pct | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pmid | int64 | primary_identifier | False | 49734 | 0 | 0.0 |  |
| pub_year | int64 | temporal | False | 7 | 0 | 0.0 |  |
| journal | str | categorical | False | 3711 | 0 | 0.0 |  |
| article_title | str | free_text | False | 49632 | 0 | 0.0 |  |
| doi | str | identifier_optional | True | 49495 | 1415 | 0.003277329219879839 |  |
| author_position | int64 | ordinal | False | 697 | 0 | 0.0 |  |
| author_role | str | categorical | False | 3 | 0 | 0.0 |  |
| author_name_raw | str | free_text | False | 263357 | 0 | 0.0 |  |
| orcid | str | identifier_optional | True | 77900 | 300604 | 0.696239062058487 |  |
| affiliation_raw | str | free_text | True | 237332 | 3616 | 0.00837513954705689 |  |
| xml_source_file | str | governance | False | 100 | 0 | 0.0 |  |
| extraction_date | str | governance | False | 1 | 0 | 0.0 |  |
| strategy_id | str | governance | False | 1 | 0 | 0.0 |  |
| source | str | governance | False | 1 | 0 | 0.0 |  |

## Dataset: `author_occurrences_unique`

| column_name | data_type | column_role | nullable | nunique | null_count | null_pct | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pmid | int64 | primary_identifier | False | 49734 | 0 | 0.0 |  |
| pub_year | int64 | temporal | False | 7 | 0 | 0.0 |  |
| journal | str | categorical | False | 3711 | 0 | 0.0 |  |
| article_title | str | free_text | False | 49632 | 0 | 0.0 |  |
| doi | str | identifier_optional | True | 49495 | 1415 | 0.0032883117366004203 |  |
| author_position | int64 | ordinal | False | 697 | 0 | 0.0 |  |
| author_role | str | categorical | False | 3 | 0 | 0.0 |  |
| author_name_raw | str | free_text | False | 263357 | 0 | 0.0 |  |
| orcid | str | identifier_optional | True | 77900 | 300168 | 0.697558980460689 |  |
| affiliation_raw | str | free_text | True | 237332 | 3599 | 0.008363698897544108 |  |
| xml_source_file | str | governance | False | 100 | 0 | 0.0 |  |
| extraction_date | str | governance | False | 1 | 0 | 0.0 |  |
| strategy_id | str | governance | False | 1 | 0 | 0.0 |  |
| source | str | governance | False | 1 | 0 | 0.0 |  |

