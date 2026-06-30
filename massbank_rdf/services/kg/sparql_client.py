from __future__ import annotations

import time
from socket import timeout as SocketTimeout
from typing import Any
from urllib.error import HTTPError, URLError

import pandas as pd
from SPARQLWrapper import JSON, POST, SPARQLWrapper
from SPARQLWrapper.SPARQLExceptions import SPARQLWrapperException


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
        max_retries: int = 3,
        retry_sleep: float = 5.0,
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.user = user
        self.password = password
        self.graph_iri = graph_iri
        self.use_from_graph = use_from_graph
        self.max_retries = max(0, int(max_retries))
        self.retry_sleep = max(0.0, float(retry_sleep))

    def select(
        self,
        query: str,
    ) -> pd.DataFrame:
        query = self._add_from_graph(query)
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                result = self._query(query)
                return self._parse_select_response(result)
            except self._retryable_exceptions() as error:
                last_error = error
                if attempt >= self.max_retries:
                    break

                sleep_seconds = self.retry_sleep * (2 ** attempt)
                print(
                    "SPARQL request failed; "
                    f"retrying {attempt + 1}/{self.max_retries} in "
                    f"{sleep_seconds:.1f}s: {error}",
                    flush=True,
                )
                time.sleep(sleep_seconds)

        if last_error is not None:
            raise last_error

        raise RuntimeError("SPARQL request failed without an exception.")

    def _query(
        self,
        query: str,
    ) -> dict[str, Any]:
        sparql = SPARQLWrapper(self.endpoint)

        sparql.setMethod(POST)
        sparql.setQuery(query)
        sparql.setReturnFormat(JSON)
        sparql.setTimeout(self.timeout)

        if self.user and self.password:
            sparql.setCredentials(self.user, self.password)

        result = sparql.query().convert()

        if not isinstance(result, dict):
            raise ValueError("SPARQL SELECT response must be a JSON object.")

        return result

    @staticmethod
    def _retryable_exceptions() -> tuple[type[Exception], ...]:
        return (
            HTTPError,
            URLError,
            TimeoutError,
            SocketTimeout,
            SPARQLWrapperException,
        )

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
