from __future__ import annotations

from typing import Any

import pandas as pd
from SPARQLWrapper import JSON, POST, SPARQLWrapper


class SparqlClient:
    """Small SPARQL SELECT client returning pandas DataFrame."""

    def __init__(
        self,
        endpoint: str,
        timeout: int = 60,
        user: str | None = None,
        password: str | None = None,
        graph_iri: str | None = None,
        use_from_graph: bool = False,
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.user = user
        self.password = password
        self.graph_iri = graph_iri
        self.use_from_graph = use_from_graph

    def select(
        self,
        query: str,
    ) -> pd.DataFrame:
        sparql = SPARQLWrapper(self.endpoint)

        sparql.setMethod(POST)
        sparql.setQuery(self._add_from_graph(query))
        sparql.setReturnFormat(JSON)
        sparql.setTimeout(self.timeout)

        if self.user and self.password:
            sparql.setCredentials(self.user, self.password)

        result = sparql.query().convert()

        return self._parse_select_response(result)

    def _add_from_graph(
        self,
        query: str,
    ) -> str:
        if not self.use_from_graph:
            return query

        if not self.graph_iri:
            return query

        if "FROM <" in query.upper():
            return query

        upper_query = query.upper()
        where_index = upper_query.find("WHERE")

        if where_index < 0:
            return query

        return (
            query[:where_index]
            + f"FROM <{self.graph_iri}>\n"
            + query[where_index:]
        )

    def _parse_select_response(
        self,
        data: dict[str, Any],
    ) -> pd.DataFrame:
        variables = data.get("head", {}).get("vars", [])
        bindings = data.get("results", {}).get("bindings", [])

        rows: list[dict[str, Any]] = []

        for binding in bindings:
            row: dict[str, Any] = {}

            for variable in variables:
                row[variable] = binding.get(variable, {}).get("value")

            rows.append(row)

        return pd.DataFrame(rows, columns=variables)