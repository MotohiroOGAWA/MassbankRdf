from __future__ import annotations

from ..common import normalize_short_inchikey_values, sparql_values


def sparql_limit_clause(limit: int | None) -> str:
    if limit is None:
        return ""

    return f"LIMIT {max(1, int(limit))}"


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
    limit: int | None = 500,
    use_short_inchikey: bool = False,
) -> str:
    from_clause = build_from_clause(use_from_graph, graph_iri)
    limit_clause = sparql_limit_clause(limit)
    if use_short_inchikey:
        query_inchikeys = normalize_short_inchikey_values(inchikeys)
        match_filter = (
            'FILTER(STRSTARTS(UCASE(STR(?value_inchikey)), '
            'CONCAT(?query_inchikey, "-")))'
        )
    else:
        query_inchikeys = inchikeys
        match_filter = "FILTER(UCASE(STR(?value_inchikey)) = ?query_inchikey)"

    return f"""
PREFIX knapsack: <http://purl.jp/knapsack/resource#>
PREFIX sio: <http://semanticscience.org/resource/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX cheminf: <http://semanticscience.org/resource/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>

SELECT
  ?value_inchikey
  ?knapsack_id
  (SAMPLE(?molecular_entity_name_value) AS ?molecular_entity_name)
  (SAMPLE(?molecular_formula_value) AS ?molecular_formula)
  (SAMPLE(?value_mw_value) AS ?value_mw)
  (SAMPLE(?activity_record_label_value) AS ?activity_record_label)
  (GROUP_CONCAT(DISTINCT STR(?activity_category_value); separator="|") AS ?activity_category)
  (GROUP_CONCAT(DISTINCT STR(?activity_function_value); separator="|") AS ?activity_function)
  (GROUP_CONCAT(DISTINCT STR(?activity_target_species_value); separator="|") AS ?activity_target_species)
  ?activity
  ?activity_label
  (GROUP_CONCAT(DISTINCT STR(?rdfs_seealso_value); separator="|") AS ?rdfs_seealso)
  (GROUP_CONCAT(DISTINCT STR(?foaf_homepage_value); separator="|") AS ?foaf_homepage)
{from_clause}
WHERE {{
  {sparql_values("query_inchikey", query_inchikeys)}

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

  {match_filter}
  FILTER(CONTAINS(STR(?StandardInchikey), "#standard_inchikey"))

  BIND(STRBEFORE(STR(?StandardInchikey), "#standard_inchikey") AS ?knapsack_record_uri)
  BIND(IRI(?knapsack_record_uri) AS ?KNApSAcKRecord)
  BIND(REPLACE(?knapsack_record_uri, "^.*/", "") AS ?knapsack_id_from_uri)

  OPTIONAL {{ ?KNApSAcKRecord dc:identifier ?knapsack_id_value . }}

  BIND(COALESCE(?knapsack_id_value, ?knapsack_id_from_uri) AS ?knapsack_id)

  OPTIONAL {{
    ?KNApSAcKRecord sio:SIO_000008 ?MolecularEntityName .
    ?MolecularEntityName a cheminf:CHEMINF_000043 ;
      sio:SIO_000300 ?molecular_entity_name_value .
  }}

  OPTIONAL {{
    ?KNApSAcKRecord sio:SIO_000008 ?MolecularFormula .
    ?MolecularFormula a cheminf:CHEMINF_000042 ;
      sio:SIO_000300 ?molecular_formula_value .
  }}

  OPTIONAL {{
    ?KNApSAcKRecord sio:SIO_000008 ?MolecularWeight .
    ?MolecularWeight a cheminf:CHEMINF_000334 ;
      sio:SIO_000300 ?value_mw_value .
  }}

  OPTIONAL {{ ?KNApSAcKRecord rdfs:seeAlso ?rdfs_seealso_value . }}
  OPTIONAL {{ ?KNApSAcKRecord foaf:homepage ?foaf_homepage_value . }}

  OPTIONAL {{
    ?KNApSAcKRecord a knapsack:KNApSAcKMetaboliteActivityRecord .
  }}

  OPTIONAL {{ ?KNApSAcKRecord rdfs:label ?activity_record_label_value . }}
  OPTIONAL {{ ?KNApSAcKRecord knapsack:category ?activity_category_value . }}
  OPTIONAL {{ ?KNApSAcKRecord knapsack:function ?activity_function_value . }}
  OPTIONAL {{ ?KNApSAcKRecord knapsack:targetsp ?activity_target_species_value . }}

  OPTIONAL {{
    ?KNApSAcKRecord sio:SIO_000225 ?activity .
    OPTIONAL {{ ?activity a knapsack:KnapsackMetaboliteActivity . }}
    OPTIONAL {{ ?activity rdfs:label ?activity_label . }}
  }}
}}
GROUP BY ?value_inchikey ?knapsack_id ?activity ?activity_label
ORDER BY ?value_inchikey ?knapsack_id ?activity_label
{limit_clause}
"""
