from __future__ import annotations

from ..common import sparql_values


def build_pubchem_compound_query(
    inchikeys: list[str],
    limit: int = 100,
) -> str:
    limit = max(1, int(limit))

    return f"""
PREFIX sio: <http://semanticscience.org/resource/>
PREFIX vocab: <http://rdf.ncbi.nlm.nih.gov/pubchem/vocabulary#>

SELECT DISTINCT
  ?value_inchikey
  ?pubchem_compound
  ?descriptorType
  ?descriptor_value
FROM <http://rdf.ncbi.nlm.nih.gov/pubchem/inchikey>
FROM <http://rdf.ncbi.nlm.nih.gov/pubchem/compound>
FROM <http://rdf.ncbi.nlm.nih.gov/pubchem/descriptor/compound>
WHERE {{
  {sparql_values("value_inchikey", inchikeys)}

  ?inchikey_node sio:SIO_000300 ?value_inchikey ;
                sio:SIO_000011 ?pubchem_compound .

  ?pubchem_compound a vocab:Compound .

  OPTIONAL {{
    ?pubchem_compound sio:SIO_000008 ?descriptor .
    ?descriptor a ?descriptorType ;
                sio:SIO_000300 ?descriptor_value .

    FILTER(?descriptorType IN (
      sio:CHEMINF_000335,
      sio:CHEMINF_000334,
      sio:CHEMINF_000376,
      sio:CHEMINF_000113
    ))
  }}
}}
LIMIT {limit}
"""


def build_pubchem_pathway_query(
    inchikeys: list[str],
    limit: int = 100,
) -> str:
    limit = max(1, int(limit))

    return f"""
PREFIX sio: <http://semanticscience.org/resource/>
PREFIX vocab: <http://rdf.ncbi.nlm.nih.gov/pubchem/vocabulary#>
PREFIX obo: <http://purl.obolibrary.org/obo/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX up: <http://purl.uniprot.org/core/>

SELECT DISTINCT
  ?value_inchikey
  ?pubchem_compound
  ?pathway
  ?pathway_label
  ?pathway_organism
FROM <http://rdf.ncbi.nlm.nih.gov/pubchem/inchikey>
FROM <http://rdf.ncbi.nlm.nih.gov/pubchem/compound>
FROM <http://rdf.ncbi.nlm.nih.gov/pubchem/pathway>
WHERE {{
  {sparql_values("value_inchikey", inchikeys)}

  ?inchikey_node sio:SIO_000300 ?value_inchikey ;
                sio:SIO_000011 ?pubchem_compound .

  ?pubchem_compound a vocab:Compound .

  ?pathway a vocab:Pathway ;
           obo:RO_0000057 ?pubchem_compound ;
           dcterms:title ?pathway_label .

  OPTIONAL {{ ?pathway up:organism ?pathway_organism . }}
}}
LIMIT {limit}
"""