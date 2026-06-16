from __future__ import annotations

from ..common import normalize_inchikey_values


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
    limit: int = 100,
) -> str:
    limit = max(1, int(limit))

    return f"""
PREFIX hmdb: <https://hmdb.ca/resource/>
PREFIX hmdbv: <https://hmdb.ca/vocab/>
PREFIX schema: <https://schema.org/>
PREFIX inchikey: <http://identifiers.org/inchikey/>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT
  ?value_inchikey
  ?hmdb_metabolite
  ?hmdb_accession
  ?hmdb_label
  ?hmdb_formula
  ?hmdb_avg_mw
  ?hmdb_mono_mw
  ?hmdb_smiles
  ?hmdb_inchi
  ?hmdb_pathway
  ?hmdb_pathway_label
  ?hmdb_disease
  ?hmdb_disease_label
  ?hmdb_biospecimen
WHERE {{
  {sparql_inchikey_uri_values("ik_uri", inchikeys)}

  ?hmdb_metabolite a hmdbv:Metabolite ;
    schema:inChIKey ?ik_uri ;
    hmdbv:accession ?hmdb_accession .

  BIND(REPLACE(STR(?ik_uri), "^.*/", "") AS ?value_inchikey)

  OPTIONAL {{ ?hmdb_metabolite rdfs:label ?hmdb_label . }}
  OPTIONAL {{ ?hmdb_metabolite hmdbv:chemicalFormula ?hmdb_formula . }}
  OPTIONAL {{ ?hmdb_metabolite hmdbv:averageMolecularWeight ?hmdb_avg_mw . }}
  OPTIONAL {{ ?hmdb_metabolite hmdbv:monoisotopicMolecularWeight ?hmdb_mono_mw . }}
  OPTIONAL {{ ?hmdb_metabolite hmdbv:smiles ?hmdb_smiles . }}
  OPTIONAL {{ ?hmdb_metabolite hmdbv:inchi ?hmdb_inchi . }}

  OPTIONAL {{
    ?hmdb_metabolite hmdbv:participatesInPathway ?hmdb_pathway .
    OPTIONAL {{ ?hmdb_pathway rdfs:label ?hmdb_pathway_label . }}
  }}

  OPTIONAL {{
    ?hmdb_metabolite hmdbv:associatedWithDisease ?hmdb_disease .
    OPTIONAL {{ ?hmdb_disease rdfs:label ?hmdb_disease_label . }}
  }}

  OPTIONAL {{ ?hmdb_metabolite hmdbv:biospecimenLocation ?hmdb_biospecimen . }}
}}
LIMIT {limit}
"""