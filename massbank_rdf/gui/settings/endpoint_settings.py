from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from massbank_rdf.services.kg import KgLookupService
from massbank_rdf.services.kg.sparql_client import SparqlClient


ENDPOINT_SETTINGS_PATH = (
    Path(__file__).resolve().parent
    / "endpoints.json"
)


@dataclass(frozen=True)
class EndpointGraphSettings:
    """Graph settings for one SPARQL endpoint."""

    enabled: bool = False
    iri: str = ""


@dataclass(frozen=True)
class EndpointAuthSettings:
    """Authentication settings for one SPARQL endpoint."""

    user: str = ""
    password: str = ""


@dataclass(frozen=True)
class EndpointSettings:
    """Settings for one SPARQL endpoint."""

    name: str
    endpoint: str
    graph: EndpointGraphSettings
    auth: EndpointAuthSettings

    @property
    def user_or_none(self) -> str | None:
        """Return user if it is not empty."""
        return self.auth.user or None

    @property
    def password_or_none(self) -> str | None:
        """Return password if it is not empty."""
        return self.auth.password or None

    @property
    def graph_iri_or_none(self) -> str | None:
        """Return graph IRI if it is not empty."""
        return self.graph.iri or None


@dataclass(frozen=True)
class EndpointSettingsBundle:
    """All endpoint settings used by GUI."""

    massbank: EndpointSettings
    pubchem: EndpointSettings
    hmdb: EndpointSettings
    knapsack: EndpointSettings


def load_endpoint_settings_json(
    path: Path | None = None,
) -> dict[str, Any]:
    """Load endpoint settings JSON."""
    settings_path = path or ENDPOINT_SETTINGS_PATH

    if not settings_path.exists():
        raise FileNotFoundError(
            f"Endpoint settings file was not found: {settings_path}"
        )

    with settings_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Endpoint settings JSON must be an object.")

    return data


def parse_graph_settings(
    data: dict[str, Any],
) -> EndpointGraphSettings:
    """Parse graph settings."""
    return EndpointGraphSettings(
        enabled=bool(data.get("enabled", False)),
        iri=str(data.get("iri", "") or ""),
    )


def parse_auth_settings(
    data: dict[str, Any],
) -> EndpointAuthSettings:
    """Parse auth settings."""
    return EndpointAuthSettings(
        user=str(data.get("user", "") or ""),
        password=str(data.get("password", "") or ""),
    )


def parse_endpoint_settings(
    data: dict[str, Any],
    *,
    key: str,
) -> EndpointSettings:
    """Parse one endpoint setting."""
    endpoint_data = data.get(key)

    if not isinstance(endpoint_data, dict):
        raise ValueError(f"Endpoint settings for '{key}' must be an object.")

    name = str(endpoint_data.get("name", key) or key)
    endpoint = str(endpoint_data.get("endpoint", "") or "")

    if not endpoint:
        raise ValueError(f"Endpoint URL for '{key}' is empty.")

    graph_data = endpoint_data.get("graph", {})
    auth_data = endpoint_data.get("auth", {})

    if not isinstance(graph_data, dict):
        graph_data = {}

    if not isinstance(auth_data, dict):
        auth_data = {}

    return EndpointSettings(
        name=name,
        endpoint=endpoint,
        graph=parse_graph_settings(graph_data),
        auth=parse_auth_settings(auth_data),
    )


def load_endpoint_settings(
    path: Path | None = None,
) -> EndpointSettingsBundle:
    """Load endpoint settings."""
    data = load_endpoint_settings_json(path)

    return EndpointSettingsBundle(
        massbank=parse_endpoint_settings(data, key="massbank"),
        pubchem=parse_endpoint_settings(data, key="pubchem"),
        hmdb=parse_endpoint_settings(data, key="hmdb"),
        knapsack=parse_endpoint_settings(data, key="knapsack"),
    )


def create_sparql_client(
    settings: EndpointSettings,
    *,
    timeout: int = 60,
) -> SparqlClient:
    """Create SPARQL client from endpoint settings."""
    return SparqlClient(
        endpoint=settings.endpoint,
        timeout=timeout,
        user=settings.user_or_none,
        password=settings.password_or_none,
        graph_iri=settings.graph_iri_or_none,
        use_from_graph=settings.graph.enabled,
    )


def create_kg_lookup_service_from_endpoint_settings(
    path: Path | None = None,
    *,
    timeout: int = 60,
) -> KgLookupService:
    """Create KG lookup service from endpoint settings."""
    settings = load_endpoint_settings(path)

    pubchem_client = create_sparql_client(
        settings.pubchem,
        timeout=timeout,
    )

    hmdb_client = create_sparql_client(
        settings.hmdb,
        timeout=timeout,
    )

    knapsack_client = create_sparql_client(
        settings.knapsack,
        timeout=timeout,
    )

    return KgLookupService(
        pubchem_client=pubchem_client,
        hmdb_client=hmdb_client,
        knapsack_client=knapsack_client,
    )