from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .basetb import Base

if TYPE_CHECKING:
    from collections.abc import Sequence


class KgInchikey(Base):
    """One InChIKey queried from MassBank and linked to KG metadata."""

    __tablename__ = "kg_inchikeys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inchikey: Mapped[str] = mapped_column(String(27), nullable=False, unique=True, index=True)

    massbank_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    example_accession_id: Mapped[str | None] = mapped_column(String, nullable=True)
    example_name: Mapped[str | None] = mapped_column(String, nullable=True)
    example_formula: Mapped[str | None] = mapped_column(String, nullable=True)

    queried_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    pubchem_compounds: Mapped[list["PubChemCompoundMetadata"]] = relationship(
        back_populates="kg_inchikey",
        cascade="all, delete-orphan",
    )
    pubchem_pathways: Mapped[list["PubChemPathwayMetadata"]] = relationship(
        back_populates="kg_inchikey",
        cascade="all, delete-orphan",
    )
    hmdb_metadata: Mapped[list["HmdbMetadata"]] = relationship(
        back_populates="kg_inchikey",
        cascade="all, delete-orphan",
    )
    knapsack_activities: Mapped[list["KnapsackActivityMetadata"]] = relationship(
        back_populates="kg_inchikey",
        cascade="all, delete-orphan",
    )
    lookup_failures: Mapped[list["KgLookupFailure"]] = relationship(
        back_populates="kg_inchikey",
        cascade="all, delete-orphan",
    )


class KgLookupFailure(Base):
    """KG lookup failure recorded so resume can skip problematic InChIKeys."""

    __tablename__ = "kg_lookup_failures"
    __table_args__ = (
        UniqueConstraint(
            "kg_inchikey_id",
            name="uq_kg_lookup_failure_inchikey",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kg_inchikey_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("kg_inchikeys.id"),
        nullable=False,
        index=True,
    )

    value_inchikey: Mapped[str] = mapped_column(String(27), nullable=False, index=True)
    error_type: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    kg_inchikey: Mapped[KgInchikey] = relationship(back_populates="lookup_failures")


class PubChemCompoundMetadata(Base):
    """PubChem compound descriptors returned by build_pubchem_compound_query."""

    __tablename__ = "pubchem_compound_metadata"
    __table_args__ = (
        UniqueConstraint(
            "kg_inchikey_id",
            "pubchem_compound",
            "descriptor_type",
            "descriptor_value",
            name="uq_pubchem_compound_metadata_row",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kg_inchikey_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("kg_inchikeys.id"),
        nullable=False,
        index=True,
    )

    value_inchikey: Mapped[str] = mapped_column(String(27), nullable=False, index=True)
    pubchem_compound: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    descriptor_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    descriptor_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    kg_inchikey: Mapped[KgInchikey] = relationship(back_populates="pubchem_compounds")


class PubChemPathwayMetadata(Base):
    """PubChem pathway rows returned by build_pubchem_pathway_query."""

    __tablename__ = "pubchem_pathway_metadata"
    __table_args__ = (
        UniqueConstraint(
            "kg_inchikey_id",
            "pubchem_compound",
            "pathway",
            "pathway_label",
            "pathway_organism",
            name="uq_pubchem_pathway_metadata_row",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kg_inchikey_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("kg_inchikeys.id"),
        nullable=False,
        index=True,
    )

    value_inchikey: Mapped[str] = mapped_column(String(27), nullable=False, index=True)
    pubchem_compound: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    pathway: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    pathway_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    pathway_organism: Mapped[str | None] = mapped_column(Text, nullable=True)

    kg_inchikey: Mapped[KgInchikey] = relationship(back_populates="pubchem_pathways")


class HmdbMetadata(Base):
    """HMDB metadata rows returned by build_hmdb_query."""

    __tablename__ = "hmdb_metadata"
    __table_args__ = (
        UniqueConstraint(
            "kg_inchikey_id",
            "hmdb_metabolite",
            "hmdb_pathway",
            "hmdb_disease",
            "hmdb_biospecimen",
            name="uq_hmdb_metadata_row",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kg_inchikey_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("kg_inchikeys.id"),
        nullable=False,
        index=True,
    )

    value_inchikey: Mapped[str] = mapped_column(String(27), nullable=False, index=True)
    hmdb_metabolite: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    hmdb_accession: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    hmdb_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    hmdb_formula: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    hmdb_avg_mw: Mapped[str | None] = mapped_column(String, nullable=True)
    hmdb_mono_mw: Mapped[str | None] = mapped_column(String, nullable=True)
    hmdb_smiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    hmdb_inchi: Mapped[str | None] = mapped_column(Text, nullable=True)
    hmdb_pathway: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    hmdb_pathway_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    hmdb_disease: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    hmdb_disease_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    hmdb_biospecimen: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)

    kg_inchikey: Mapped[KgInchikey] = relationship(back_populates="hmdb_metadata")


class KnapsackActivityMetadata(Base):
    """KNApSAcK activity rows returned by build_knapsack_activity_query."""

    __tablename__ = "knapsack_activity_metadata"
    __table_args__ = (
        UniqueConstraint(
            "kg_inchikey_id",
            "knapsack_id",
            "activity",
            "activity_label",
            "activity_category",
            "activity_function",
            "activity_target_species",
            name="uq_knapsack_activity_metadata_row",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kg_inchikey_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("kg_inchikeys.id"),
        nullable=False,
        index=True,
    )

    value_inchikey: Mapped[str] = mapped_column(String(27), nullable=False, index=True)
    knapsack_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    molecular_entity_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    molecular_formula: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    value_mw: Mapped[str | None] = mapped_column(String, nullable=True)
    activity_record_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    activity_category: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    activity_function: Mapped[str | None] = mapped_column(Text, nullable=True)
    activity_target_species: Mapped[str | None] = mapped_column(Text, nullable=True)
    activity: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    activity_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    rdfs_seealso: Mapped[str | None] = mapped_column(Text, nullable=True)
    foaf_homepage: Mapped[str | None] = mapped_column(Text, nullable=True)

    kg_inchikey: Mapped[KgInchikey] = relationship(back_populates="knapsack_activities")
