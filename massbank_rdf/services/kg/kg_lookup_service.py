from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from massbank_rdf.services.kg.common import (
    ensure_columns,
    extract_inchikey_value,
    normalize_inchikey_values,
)
from massbank_rdf.services.kg.sparql_client import SparqlClient
from massbank_rdf.services.kg.query_builders.hmdb_query_builder import (
    build_hmdb_query,
)
from massbank_rdf.services.kg.query_builders.knapsack_query_builder import (
    build_knapsack_activity_query,
)
from massbank_rdf.services.kg.query_builders.pubchem_query_builder import (
    build_pubchem_compound_query,
    build_pubchem_pathway_query,
)


@dataclass(frozen=True)
class KgLookupConfig:
    """SPARQL endpoint configuration for KG lookup."""

    pubchem_endpoint: str
    hmdb_endpoint: str
    knapsack_endpoint: str

    timeout: int = 60

    pubchem_user: str | None = None
    pubchem_password: str | None = None

    hmdb_user: str | None = None
    hmdb_password: str | None = None

    knapsack_user: str | None = None
    knapsack_password: str | None = None
    knapsack_graph_iri: str | None = None
    knapsack_use_from_graph: bool = False


class KgLookupService:
    """Lookup KG evidence from InChIKey values."""

    def __init__(
        self,
        pubchem_client: SparqlClient,
        hmdb_client: SparqlClient,
        knapsack_client: SparqlClient,
    ) -> None:
        self.pubchem_client = pubchem_client
        self.hmdb_client = hmdb_client
        self.knapsack_client = knapsack_client

    @classmethod
    def from_config(
        cls,
        config: KgLookupConfig,
    ) -> "KgLookupService":
        """Create service from endpoint configuration."""
        pubchem_client = SparqlClient(
            endpoint=config.pubchem_endpoint,
            timeout=config.timeout,
            user=config.pubchem_user,
            password=config.pubchem_password,
        )

        hmdb_client = SparqlClient(
            endpoint=config.hmdb_endpoint,
            timeout=config.timeout,
            user=config.hmdb_user,
            password=config.hmdb_password,
        )

        knapsack_client = SparqlClient(
            endpoint=config.knapsack_endpoint,
            timeout=config.timeout,
            user=config.knapsack_user,
            password=config.knapsack_password,
            graph_iri=config.knapsack_graph_iri,
            use_from_graph=config.knapsack_use_from_graph,
        )

        return cls(
            pubchem_client=pubchem_client,
            hmdb_client=hmdb_client,
            knapsack_client=knapsack_client,
        )

    def search_by_massbank_records(
        self,
        massbank_result_df: pd.DataFrame,
        *,
        inchikey_column: str = "inchikey",
        top_n: int = 10,
        kg_n: int = 3,
        limit: int | None = 100,
        return_query: bool = False,
    ):
        """Search KG evidence by InChIKeys in MassBank search result table.

        Parameters
        ----------
        massbank_result_df:
            Display or internal MassBank result DataFrame.
            It should contain an InChIKey column.
        inchikey_column:
            Column name containing InChIKey values.
        top_n:
            Number of top MassBank rows considered.
        kg_n:
            Maximum number of unique InChIKeys used for KG lookup.
        limit:
            SPARQL result limit per source.
        return_query:
            Whether to also return generated SPARQL queries.
        """
        inchikeys = self.extract_inchikeys_from_massbank_records(
            massbank_result_df,
            inchikey_column=inchikey_column,
            top_n=top_n,
            kg_n=kg_n,
        )

        return self.search_by_inchikeys(
            inchikeys,
            limit=limit,
            return_query=return_query,
        )

    def extract_inchikeys_from_massbank_records(
        self,
        massbank_result_df: pd.DataFrame,
        *,
        inchikey_column: str = "inchikey",
        top_n: int = 10,
        kg_n: int = 3,
    ) -> list[str]:
        """Extract normalized InChIKeys from MassBank result DataFrame."""
        if massbank_result_df.empty:
            return []

        if inchikey_column not in massbank_result_df.columns:
            return []

        data = massbank_result_df.copy()

        # Keep display order. Usually result is already sorted by score.
        data = data.head(max(1, int(top_n)))

        inchikeys = [
            extract_inchikey_value(value)
            for value in data[inchikey_column].tolist()
        ]

        inchikeys = [
            value
            for value in inchikeys
            if value is not None
        ]

        return normalize_inchikey_values(inchikeys)[: max(1, int(kg_n))]

    def search_by_inchikey(
        self,
        inchikey: str,
        *,
        limit: int | None = 100,
        return_query: bool = False,
    ):
        """Search KG evidence by one InChIKey."""
        return self.search_by_inchikeys(
            [inchikey],
            limit=limit,
            return_query=return_query,
        )

    def search_by_inchikeys(
        self,
        inchikeys: list[str],
        *,
        limit: int | None = 100,
        return_query: bool = False,
    ):
        """Search KG evidence by multiple InChIKeys."""
        inchikeys = normalize_inchikey_values(inchikeys)

        if len(inchikeys) == 0:
            data = self._empty_result()
            queries = self._empty_queries()

            if return_query:
                return data, queries
            return data

        pubchem_compound_query = build_pubchem_compound_query(
            inchikeys,
            limit=limit,
        )
        pubchem_pathway_query = build_pubchem_pathway_query(
            inchikeys,
            limit=limit,
        )
        hmdb_query = build_hmdb_query(
            inchikeys,
            limit=limit,
        )
        knapsack_activity_query = build_knapsack_activity_query(
            inchikeys,
            use_from_graph=self.knapsack_client.use_from_graph,
            graph_iri=self.knapsack_client.graph_iri or "",
            limit=limit,
        )

        pubchem_compound_data = self.pubchem_client.select(
            pubchem_compound_query
        )
        pubchem_pathway_data = self.pubchem_client.select(
            pubchem_pathway_query
        )
        hmdb_data = self.hmdb_client.select(
            hmdb_query
        )
        knapsack_activity_data = self.knapsack_client.select(
            knapsack_activity_query
        )

        data = {
            "pubchem_compound": self._format_pubchem_compound_data(
                pubchem_compound_data
            ),
            "pubchem_pathway": self._format_pubchem_pathway_data(
                pubchem_pathway_data
            ),
            "hmdb": self._format_hmdb_data(
                hmdb_data
            ),
            "knapsack_activity": self._format_knapsack_activity_data(
                knapsack_activity_data
            ),
        }

        queries = {
            "pubchem_compound": pubchem_compound_query,
            "pubchem_pathway": pubchem_pathway_query,
            "hmdb": hmdb_query,
            "knapsack_activity": knapsack_activity_query,
        }

        if return_query:
            return data, queries

        return data

    def _empty_result(
        self,
    ) -> dict[str, pd.DataFrame]:
        return {
            "pubchem_compound": pd.DataFrame(),
            "pubchem_pathway": pd.DataFrame(),
            "hmdb": pd.DataFrame(),
            "knapsack_activity": pd.DataFrame(),
        }

    def _empty_queries(
        self,
    ) -> dict[str, str]:
        return {
            "pubchem_compound": "",
            "pubchem_pathway": "",
            "hmdb": "",
            "knapsack_activity": "",
        }

    def _normalize_value_inchikey_column(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        df = df.copy()

        if "value_inchikey" in df.columns:
            df["value_inchikey"] = df["value_inchikey"].apply(
                extract_inchikey_value
            )

        return df

    def _format_pubchem_compound_data(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        df = ensure_columns(
            df,
            [
                "value_inchikey",
                "pubchem_compound",
                "descriptorType",
                "descriptor_value",
            ],
        )
        return self._normalize_value_inchikey_column(df)

    def _format_pubchem_pathway_data(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        df = ensure_columns(
            df,
            [
                "value_inchikey",
                "pubchem_compound",
                "pathway",
                "pathway_label",
                "pathway_organism",
            ],
        )
        return self._normalize_value_inchikey_column(df)

    def _format_hmdb_data(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        df = ensure_columns(
            df,
            [
                "value_inchikey",
                "hmdb_metabolite",
                "hmdb_accession",
                "hmdb_label",
                "hmdb_formula",
                "hmdb_avg_mw",
                "hmdb_mono_mw",
                "hmdb_smiles",
                "hmdb_inchi",
                "hmdb_pathway",
                "hmdb_pathway_label",
                "hmdb_disease",
                "hmdb_disease_label",
                "hmdb_biospecimen",
            ],
        )
        return self._normalize_value_inchikey_column(df)

    def _format_knapsack_activity_data(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        df = ensure_columns(
            df,
            [
                "value_inchikey",
                "knapsack_id",
                "molecular_entity_name",
                "molecular_formula",
                "value_mw",
                "activity_record_label",
                "activity_category",
                "activity_function",
                "activity_target_species",
                "activity",
                "activity_label",
                "rdfs_seealso",
                "foaf_homepage",
            ],
        )
        return self._normalize_value_inchikey_column(df)