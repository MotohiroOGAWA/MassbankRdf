from __future__ import annotations

import unittest
from dataclasses import dataclass, field

import pandas as pd

from massbank_rdf.services.kg.kg_lookup_service import KgLookupService


@dataclass
class FakeSparqlClient:
    """Fake SPARQL client for unit tests."""

    response_df: pd.DataFrame
    use_from_graph: bool = False
    graph_iri: str | None = None
    queries: list[str] = field(default_factory=list)

    def select(self, query: str) -> pd.DataFrame:
        self.queries.append(query)
        return self.response_df.copy()


class TestKgLookupService(unittest.TestCase):
    """Unit tests for KgLookupService."""

    def _make_service(self) -> KgLookupService:
        pubchem_compound_df = pd.DataFrame(
            [
                {
                    "value_inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
                    "pubchem_compound": "http://rdf.ncbi.nlm.nih.gov/pubchem/compound/CID123",
                    "descriptorType": "http://semanticscience.org/resource/CHEMINF_000335",
                    "descriptor_value": "C6H8O6",
                }
            ]
        )

        hmdb_df = pd.DataFrame(
            [
                {
                    "value_inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
                    "hmdb_metabolite": "https://hmdb.ca/metabolites/HMDB0000044",
                    "hmdb_accession": "HMDB0000044",
                    "hmdb_label": "Ascorbic acid",
                    "hmdb_formula": "C6H8O6",
                }
            ]
        )

        knapsack_df = pd.DataFrame(
            [
                {
                    "value_inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
                    "knapsack_id": "C00000001",
                    "molecular_entity_name": "Ascorbic acid",
                    "activity_category": "example category",
                    "activity_label": "example activity",
                }
            ]
        )

        self.pubchem_client = FakeSparqlClient(pubchem_compound_df)
        self.hmdb_client = FakeSparqlClient(hmdb_df)
        self.knapsack_client = FakeSparqlClient(
            knapsack_df,
            use_from_graph=True,
            graph_iri="http://example.org/graph/knapsack",
        )

        return KgLookupService(
            pubchem_client=self.pubchem_client,
            hmdb_client=self.hmdb_client,
            knapsack_client=self.knapsack_client,
        )

    def test_search_by_inchikey_returns_kg_tables(self) -> None:
        """search_by_inchikey should return KG DataFrames for one InChIKey."""
        service = self._make_service()

        result = service.search_by_inchikey(
            "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            limit=10,
        )

        self.assertIsInstance(result, dict)
        self.assertIn("pubchem_compound", result)
        self.assertIn("pubchem_pathway", result)
        self.assertIn("hmdb", result)
        self.assertIn("knapsack_activity", result)

        self.assertIsInstance(result["pubchem_compound"], pd.DataFrame)
        self.assertIsInstance(result["pubchem_pathway"], pd.DataFrame)
        self.assertIsInstance(result["hmdb"], pd.DataFrame)
        self.assertIsInstance(result["knapsack_activity"], pd.DataFrame)

        self.assertEqual(
            result["pubchem_compound"].iloc[0]["value_inchikey"],
            "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
        )
        self.assertEqual(
            result["hmdb"].iloc[0]["hmdb_accession"],
            "HMDB0000044",
        )
        self.assertEqual(
            result["knapsack_activity"].iloc[0]["knapsack_id"],
            "C00000001",
        )

    def test_search_by_inchikey_calls_all_sparql_clients(self) -> None:
        """search_by_inchikey should call PubChem, HMDB, and KNApSAcK clients."""
        service = self._make_service()

        service.search_by_inchikey(
            "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            limit=10,
        )

        # PubChem client is used for compound and pathway queries.
        self.assertEqual(len(self.pubchem_client.queries), 2)

        # HMDB and KNApSAcK clients are used once each.
        self.assertEqual(len(self.hmdb_client.queries), 1)
        self.assertEqual(len(self.knapsack_client.queries), 1)

        all_queries = "\n".join(
            [
                *self.pubchem_client.queries,
                *self.hmdb_client.queries,
                *self.knapsack_client.queries,
            ]
        )

        self.assertIn("BSYNRYMUTXBXSQ-UHFFFAOYSA-N", all_queries)

    def test_search_by_inchikeys_normalizes_input_inchikeys(self) -> None:
        """search_by_inchikeys should normalize and deduplicate InChIKeys."""
        service = self._make_service()

        service.search_by_inchikeys(
            [
                "prefix BSYNRYMUTXBXSQ-UHFFFAOYSA-N suffix",
                "bsynrymutxbxsq-uhfffaoysa-n",
                "invalid",
            ],
            limit=10,
        )

        all_queries = "\n".join(
            [
                *self.pubchem_client.queries,
                *self.hmdb_client.queries,
                *self.knapsack_client.queries,
            ]
        )

        self.assertIn("BSYNRYMUTXBXSQ-UHFFFAOYSA-N", all_queries)
        self.assertNotIn("invalid", all_queries)

    def test_search_by_inchikeys_can_match_short_inchikey(self) -> None:
        """Short mode should query every source by the connectivity block."""
        service = self._make_service()

        service.search_by_inchikeys(
            ["BSYNRYMUTXBXSQ-UHFFFAOYSA-N"],
            limit=10,
            use_short_inchikey=True,
        )

        all_queries = [
            *self.pubchem_client.queries,
            *self.hmdb_client.queries,
            *self.knapsack_client.queries,
        ]

        self.assertEqual(len(all_queries), 4)
        for query in all_queries:
            self.assertIn('"BSYNRYMUTXBXSQ"', query)
            self.assertIn("STRSTARTS", query)
            self.assertNotIn('"BSYNRYMUTXBXSQ-UHFFFAOYSA-N"', query)

    def test_search_by_inchikeys_uses_full_match_by_default(self) -> None:
        """The existing full-InChIKey matching remains the default."""
        service = self._make_service()

        service.search_by_inchikeys(
            ["BSYNRYMUTXBXSQ-UHFFFAOYSA-N"],
            limit=10,
        )

        all_queries = "\n".join(
            [
                *self.pubchem_client.queries,
                *self.hmdb_client.queries,
                *self.knapsack_client.queries,
            ]
        )

        self.assertIn("BSYNRYMUTXBXSQ-UHFFFAOYSA-N", all_queries)
        self.assertNotIn("STRSTARTS", all_queries)

    def test_search_by_inchikeys_empty_input_returns_empty_tables(self) -> None:
        """search_by_inchikeys should return empty tables for invalid input."""
        service = self._make_service()

        result = service.search_by_inchikeys(
            ["invalid-inchi-key"],
            limit=10,
        )

        self.assertEqual(len(self.pubchem_client.queries), 0)
        self.assertEqual(len(self.hmdb_client.queries), 0)
        self.assertEqual(len(self.knapsack_client.queries), 0)

        self.assertIn("pubchem_compound", result)
        self.assertIn("pubchem_pathway", result)
        self.assertIn("hmdb", result)
        self.assertIn("knapsack_activity", result)

        for df in result.values():
            self.assertIsInstance(df, pd.DataFrame)
            self.assertTrue(df.empty)

    def test_search_by_inchikey_returns_queries_when_requested(self) -> None:
        """search_by_inchikey should return data and query dict when return_query=True."""
        service = self._make_service()

        data, queries = service.search_by_inchikey(
            "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            limit=10,
            return_query=True,
        )

        self.assertIsInstance(data, dict)
        self.assertIsInstance(queries, dict)

        self.assertIn("pubchem_compound", queries)
        self.assertIn("pubchem_pathway", queries)
        self.assertIn("hmdb", queries)
        self.assertIn("knapsack_activity", queries)

        self.assertIn("BSYNRYMUTXBXSQ-UHFFFAOYSA-N", queries["pubchem_compound"])
        self.assertIn("BSYNRYMUTXBXSQ-UHFFFAOYSA-N", queries["hmdb"])

    def test_search_by_massbank_records_extracts_inchikey_column(self) -> None:
        """search_by_massbank_records should use InChIKeys from MassBank result table."""
        service = self._make_service()

        massbank_result_df = pd.DataFrame(
            [
                {
                    "score": 0.98,
                    "match": 5,
                    "accession_id": "MSBNK-TEST-0001",
                    "inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
                },
                {
                    "score": 0.91,
                    "match": 4,
                    "accession_id": "MSBNK-TEST-0002",
                    "inchikey": "invalid",
                },
            ]
        )

        result = service.search_by_massbank_records(
            massbank_result_df,
            inchikey_column="inchikey",
            top_n=10,
            kg_n=3,
            limit=10,
        )

        self.assertIn("hmdb", result)
        self.assertFalse(result["hmdb"].empty)

        all_queries = "\n".join(
            [
                *self.pubchem_client.queries,
                *self.hmdb_client.queries,
                *self.knapsack_client.queries,
            ]
        )

        self.assertIn("BSYNRYMUTXBXSQ-UHFFFAOYSA-N", all_queries)
        self.assertNotIn("invalid", all_queries)

    def test_extract_inchikeys_from_massbank_records_respects_kg_n(self) -> None:
        """extract_inchikeys_from_massbank_records should limit unique InChIKeys."""
        service = self._make_service()

        massbank_result_df = pd.DataFrame(
            [
                {"inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"},
                {"inchikey": "XLYOFNOQVPJJNP-UHFFFAOYSA-N"},
                {"inchikey": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"},
            ]
        )

        inchikeys = service.extract_inchikeys_from_massbank_records(
            massbank_result_df,
            inchikey_column="inchikey",
            top_n=10,
            kg_n=2,
        )

        self.assertEqual(
            inchikeys,
            [
                "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
                "XLYOFNOQVPJJNP-UHFFFAOYSA-N",
            ],
        )


if __name__ == "__main__":
    unittest.main()
