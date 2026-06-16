from __future__ import annotations

from ..common import sparql_values


def build_from_clause(
    use_from_graph: bool,
    graph_iri: str | None,
) -> str:
    if not use_from_graph:
        return ""

    if graph_iri is None or graph_iri == "":
        return ""

    return f"FROM <{graph_iri}>"


def build_knapsack_activity_query(
    inchikeys: list[str],
    use_from_graph: bool = True,
    graph_iri: str = "http://example.org/graph/knapsack",
    limit: int = 500,
) -> str:
    limit = max(1, int(limit))
    from_clause = build_from_clause(use_from_graph, graph_iri)

    return f"""
PREFIX knapsack: <http://purl.jp/knapsack/resource#>
PREFIX sio: <http://semanticscience.org/resource/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX cheminf: <http://semanticscience.org/resource/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>

SELECT DISTINCT
  ?value_inchikey
  ?knapsack_id
  ?molecular_entity_name
  ?molecular_formula
  ?value_mw
  ?activity_record_label
  ?activity_category
  ?activity_function
  ?activity_target_species
  ?activity
  ?activity_label
  ?rdfs_seealso
  ?foaf_homepage
{from_clause}
WHERE {{
  {sparql_values("query_inchikey", inchikeys)}

  {{
    ?StandardInchikey a cheminf:CHEMINF_000059 ;
      sio:SIO_000300 ?value_inchikey .
  }}
  UNION
  {{
    GRAPH ?inchikey_graph {{
      ?StandardInchikey a cheminf:CHEMINF_000059 ;
        sio:SIO_000300 ?value_inchikey .
    }}
  }}

  FILTER(UCASE(STR(?value_inchikey)) = ?query_inchikey)
  FILTER(CONTAINS(STR(?StandardInchikey), "#standard_inchikey"))

  BIND(STRBEFORE(STR(?StandardInchikey), "#standard_inchikey") AS ?knapsack_record_uri)
  BIND(IRI(?knapsack_record_uri) AS ?KNApSAcKRecord)
  BIND(REPLACE(?knapsack_record_uri, "^.*/", "") AS ?knapsack_id_from_uri)

  OPTIONAL {{ ?KNApSAcKRecord dc:identifier ?knapsack_id_value . }}

  BIND(COALESCE(?knapsack_id_value, ?knapsack_id_from_uri) AS ?knapsack_id)

  OPTIONAL {{
    ?KNApSAcKRecord sio:SIO_000008 ?MolecularEntityName .
    ?MolecularEntityName a cheminf:CHEMINF_000043 ;
      sio:SIO_000300 ?molecular_entity_name .
  }}

  OPTIONAL {{
    ?KNApSAcKRecord sio:SIO_000008 ?MolecularFormula .
    ?MolecularFormula a cheminf:CHEMINF_000042 ;
      sio:SIO_000300 ?molecular_formula .
  }}

  OPTIONAL {{
    ?KNApSAcKRecord sio:SIO_000008 ?MolecularWeight .
    ?MolecularWeight a cheminf:CHEMINF_000334 ;
      sio:SIO_000300 ?value_mw .
  }}

  OPTIONAL {{ ?KNApSAcKRecord rdfs:seeAlso ?rdfs_seealso . }}
  OPTIONAL {{ ?KNApSAcKRecord foaf:homepage ?foaf_homepage . }}

  OPTIONAL {{
    ?KNApSAcKRecord a knapsack:KNApSAcKMetaboliteActivityRecord .
  }}

  OPTIONAL {{ ?KNApSAcKRecord rdfs:label ?activity_record_label . }}
  OPTIONAL {{ ?KNApSAcKRecord knapsack:category ?activity_category . }}
  OPTIONAL {{ ?KNApSAcKRecord knapsack:function ?activity_function . }}
  OPTIONAL {{ ?KNApSAcKRecord knapsack:targetsp ?activity_target_species . }}

  OPTIONAL {{
    ?KNApSAcKRecord sio:SIO_000225 ?activity .
    OPTIONAL {{ ?activity a knapsack:KnapsackMetaboliteActivity . }}
    OPTIONAL {{ ?activity rdfs:label ?activity_label . }}
  }}
}}
ORDER BY ?value_inchikey ?knapsack_id ?activity_label
LIMIT {limit}
"""