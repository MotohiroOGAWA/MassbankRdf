from __future__ import annotations

from ..common import (
    normalize_inchikey_values,
    normalize_short_inchikey_values,
    sparql_values,
)


def sparql_limit_clause(limit: int | None) -> str:
    if limit is None:
        return ""

    return f"LIMIT {max(1, int(limit))}"


def sparql_inchikey_uri_values(
    variable: str,
    inchikeys: list[str],
) -> str:
    inchikeys = normalize_inchikey_values(inchikeys)

    if len(inchikeys) == 0:
        return f"VALUES ?{variable} {{ }}"

    values = " ".join(
        f"inchikey:{inchikey}"
        for inchikey in inchikeys
    )

    return f"VALUES ?{variable} {{ {values} }}"


def build_hmdb_query(
    inchikeys: list[str],
    limit: int | None = 100,
    use_short_inchikey: bool = False,
) -> str:
    limit_clause = sparql_limit_clause(limit)
    if use_short_inchikey:
        inchikey_values = sparql_values(
            "query_short_inchikey",
            normalize_short_inchikey_values(inchikeys),
        )
        inchikey_filter = (
            'FILTER(STRSTARTS(UCASE(?value_inchikey), '
            'CONCAT(?query_short_inchikey, "-")))'
        )
    else:
        inchikey_values = sparql_inchikey_uri_values("ik_uri", inchikeys)
        inchikey_filter = ""

    return f"""
PREFIX hmdb: <https://hmdb.ca/resource/>
PREFIX hmdbv: <https://hmdb.ca/vocab/>
PREFIX schema: <https://schema.org/>
PREFIX inchikey: <http://identifiers.org/inchikey/>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT
  ?value_inchikey
  ?hmdb_metabolite
  ?hmdb_accession
  (SAMPLE(?hmdb_label_value) AS ?hmdb_label)
  (SAMPLE(?hmdb_formula_value) AS ?hmdb_formula)
  (SAMPLE(?hmdb_avg_mw_value) AS ?hmdb_avg_mw)
  (SAMPLE(?hmdb_mono_mw_value) AS ?hmdb_mono_mw)
  (SAMPLE(?hmdb_smiles_value) AS ?hmdb_smiles)
  (SAMPLE(?hmdb_inchi_value) AS ?hmdb_inchi)
  (GROUP_CONCAT(DISTINCT STR(?hmdb_pathway_value); separator="|") AS ?hmdb_pathway)
  (GROUP_CONCAT(DISTINCT STR(?hmdb_pathway_label_value); separator="|") AS ?hmdb_pathway_label)
  (GROUP_CONCAT(DISTINCT STR(?hmdb_disease_value); separator="|") AS ?hmdb_disease)
  (GROUP_CONCAT(DISTINCT STR(?hmdb_disease_label_value); separator="|") AS ?hmdb_disease_label)
  (GROUP_CONCAT(DISTINCT STR(?hmdb_biospecimen_value); separator="|") AS ?hmdb_biospecimen)
WHERE {{
  {inchikey_values}

  ?hmdb_metabolite a hmdbv:Metabolite ;
    schema:inChIKey ?ik_uri ;
    hmdbv:accession ?hmdb_accession .

  BIND(REPLACE(STR(?ik_uri), "^.*/", "") AS ?value_inchikey)
  {inchikey_filter}

  OPTIONAL {{ ?hmdb_metabolite rdfs:label ?hmdb_label_value . }}
  OPTIONAL {{ ?hmdb_metabolite hmdbv:chemicalFormula ?hmdb_formula_value . }}
  OPTIONAL {{ ?hmdb_metabolite hmdbv:averageMolecularWeight ?hmdb_avg_mw_value . }}
  OPTIONAL {{ ?hmdb_metabolite hmdbv:monoisotopicMolecularWeight ?hmdb_mono_mw_value . }}
  OPTIONAL {{ ?hmdb_metabolite hmdbv:smiles ?hmdb_smiles_value . }}
  OPTIONAL {{ ?hmdb_metabolite hmdbv:inchi ?hmdb_inchi_value . }}

  OPTIONAL {{
    ?hmdb_metabolite hmdbv:participatesInPathway ?hmdb_pathway_value .
    OPTIONAL {{ ?hmdb_pathway_value rdfs:label ?hmdb_pathway_label_value . }}
  }}

  OPTIONAL {{
    ?hmdb_metabolite hmdbv:associatedWithDisease ?hmdb_disease_value .
    OPTIONAL {{ ?hmdb_disease_value rdfs:label ?hmdb_disease_label_value . }}
  }}

  OPTIONAL {{ ?hmdb_metabolite hmdbv:biospecimenLocation ?hmdb_biospecimen_value . }}
}}
GROUP BY ?value_inchikey ?hmdb_metabolite ?hmdb_accession
{limit_clause}
"""
