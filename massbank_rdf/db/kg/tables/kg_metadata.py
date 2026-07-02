from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .basetb import Base


class KgInchikey(Base):
    """One normalized MassBank InChIKey used as the local KG lookup key."""

    __tablename__ = "kg_inchikeys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inchikey: Mapped[str] = mapped_column(String(27), nullable=False, unique=True, index=True)

    massbank_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    example_accession_id: Mapped[str | None] = mapped_column(String, nullable=True)
    example_name: Mapped[str | None] = mapped_column(String, nullable=True)
    example_formula: Mapped[str | None] = mapped_column(String, nullable=True)

    queried_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lookup_failures: Mapped[list["KgLookupFailure"]] = relationship(
        back_populates="kg_inchikey",
        cascade="all, delete-orphan",
    )


class KgLookupFailure(Base):
    """KG lookup failure recorded so resume can skip problematic InChIKeys."""

    __tablename__ = "kg_lookup_failures"
    __table_args__ = (
        UniqueConstraint("kg_inchikey_id", name="uq_kg_lookup_failure_inchikey"),
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


class PubChemCompound(Base):
    __tablename__ = "pubchem_compounds"
    __table_args__ = (
        UniqueConstraint("uri", name="uq_pubchem_compound_uri"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uri: Mapped[str] = mapped_column(Text, nullable=False, index=True)


class PubChemCompoundInchikey(Base):
    __tablename__ = "pubchem_compound_inchikeys"
    __table_args__ = (
        UniqueConstraint(
            "kg_inchikey_id",
            "pubchem_compound_id",
            name="uq_pubchem_compound_inchikey",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kg_inchikey_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("kg_inchikeys.id"),
        nullable=False,
        index=True,
    )
    pubchem_compound_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("pubchem_compounds.id"),
        nullable=False,
        index=True,
    )


class PubChemDescriptorType(Base):
    __tablename__ = "pubchem_descriptor_types"
    __table_args__ = (
        UniqueConstraint("uri", name="uq_pubchem_descriptor_type_uri"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uri: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)


class PubChemCompoundDescriptor(Base):
    __tablename__ = "pubchem_compound_descriptors"
    __table_args__ = (
        UniqueConstraint(
            "pubchem_compound_id",
            "descriptor_type_id",
            "descriptor_value",
            name="uq_pubchem_compound_descriptor",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pubchem_compound_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("pubchem_compounds.id"),
        nullable=False,
        index=True,
    )
    descriptor_type_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("pubchem_descriptor_types.id"),
        nullable=False,
        index=True,
    )
    descriptor_value: Mapped[str] = mapped_column(Text, nullable=False)


class PubChemPathway(Base):
    __tablename__ = "pubchem_pathways"
    __table_args__ = (
        UniqueConstraint("uri", name="uq_pubchem_pathway_uri"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uri: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    organism_uri: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)


class PubChemCompoundPathway(Base):
    __tablename__ = "pubchem_compound_pathways"
    __table_args__ = (
        UniqueConstraint(
            "pubchem_compound_id",
            "pubchem_pathway_id",
            name="uq_pubchem_compound_pathway",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pubchem_compound_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("pubchem_compounds.id"),
        nullable=False,
        index=True,
    )
    pubchem_pathway_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("pubchem_pathways.id"),
        nullable=False,
        index=True,
    )


class HmdbMetabolite(Base):
    __tablename__ = "hmdb_metabolites"
    __table_args__ = (
        UniqueConstraint("uri", name="uq_hmdb_metabolite_uri"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uri: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    accession: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    formula: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    average_molecular_weight: Mapped[str | None] = mapped_column(String, nullable=True)
    monoisotopic_molecular_weight: Mapped[str | None] = mapped_column(String, nullable=True)
    smiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    inchi: Mapped[str | None] = mapped_column(Text, nullable=True)


class HmdbMetaboliteInchikey(Base):
    __tablename__ = "hmdb_metabolite_inchikeys"
    __table_args__ = (
        UniqueConstraint(
            "kg_inchikey_id",
            "hmdb_metabolite_id",
            name="uq_hmdb_metabolite_inchikey",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kg_inchikey_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("kg_inchikeys.id"),
        nullable=False,
        index=True,
    )
    hmdb_metabolite_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("hmdb_metabolites.id"),
        nullable=False,
        index=True,
    )


class HmdbPathway(Base):
    __tablename__ = "hmdb_pathways"
    __table_args__ = (
        UniqueConstraint("uri", name="uq_hmdb_pathway_uri"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uri: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)


class HmdbMetabolitePathway(Base):
    __tablename__ = "hmdb_metabolite_pathways"
    __table_args__ = (
        UniqueConstraint(
            "hmdb_metabolite_id",
            "hmdb_pathway_id",
            name="uq_hmdb_metabolite_pathway",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hmdb_metabolite_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("hmdb_metabolites.id"),
        nullable=False,
        index=True,
    )
    hmdb_pathway_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("hmdb_pathways.id"),
        nullable=False,
        index=True,
    )


class HmdbDisease(Base):
    __tablename__ = "hmdb_diseases"
    __table_args__ = (
        UniqueConstraint("uri", name="uq_hmdb_disease_uri"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uri: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)


class HmdbMetaboliteDisease(Base):
    __tablename__ = "hmdb_metabolite_diseases"
    __table_args__ = (
        UniqueConstraint(
            "hmdb_metabolite_id",
            "hmdb_disease_id",
            name="uq_hmdb_metabolite_disease",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hmdb_metabolite_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("hmdb_metabolites.id"),
        nullable=False,
        index=True,
    )
    hmdb_disease_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("hmdb_diseases.id"),
        nullable=False,
        index=True,
    )


class HmdbBiospecimen(Base):
    __tablename__ = "hmdb_biospecimens"
    __table_args__ = (
        UniqueConstraint("name", name="uq_hmdb_biospecimen_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)


class HmdbMetaboliteBiospecimen(Base):
    __tablename__ = "hmdb_metabolite_biospecimens"
    __table_args__ = (
        UniqueConstraint(
            "hmdb_metabolite_id",
            "hmdb_biospecimen_id",
            name="uq_hmdb_metabolite_biospecimen",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hmdb_metabolite_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("hmdb_metabolites.id"),
        nullable=False,
        index=True,
    )
    hmdb_biospecimen_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("hmdb_biospecimens.id"),
        nullable=False,
        index=True,
    )


class KnapsackRecord(Base):
    __tablename__ = "knapsack_records"
    __table_args__ = (
        UniqueConstraint("knapsack_id", name="uq_knapsack_record_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knapsack_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    molecular_entity_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    molecular_formula: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    molecular_weight: Mapped[str | None] = mapped_column(String, nullable=True)
    activity_record_label: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnapsackRecordInchikey(Base):
    __tablename__ = "knapsack_record_inchikeys"
    __table_args__ = (
        UniqueConstraint(
            "kg_inchikey_id",
            "knapsack_record_id",
            name="uq_knapsack_record_inchikey",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kg_inchikey_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("kg_inchikeys.id"),
        nullable=False,
        index=True,
    )
    knapsack_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knapsack_records.id"),
        nullable=False,
        index=True,
    )


class KnapsackActivity(Base):
    __tablename__ = "knapsack_activities"
    __table_args__ = (
        UniqueConstraint("uri", name="uq_knapsack_activity_uri"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uri: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnapsackRecordActivity(Base):
    __tablename__ = "knapsack_record_activities"
    __table_args__ = (
        UniqueConstraint(
            "knapsack_record_id",
            "knapsack_activity_id",
            name="uq_knapsack_record_activity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knapsack_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knapsack_records.id"),
        nullable=False,
        index=True,
    )
    knapsack_activity_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knapsack_activities.id"),
        nullable=False,
        index=True,
    )


class KnapsackActivityCategory(Base):
    __tablename__ = "knapsack_activity_categories"
    __table_args__ = (
        UniqueConstraint("name", name="uq_knapsack_activity_category_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)


class KnapsackRecordActivityCategory(Base):
    __tablename__ = "knapsack_record_activity_categories"
    __table_args__ = (
        UniqueConstraint(
            "knapsack_record_id",
            "category_id",
            name="uq_knapsack_record_activity_category",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knapsack_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knapsack_records.id"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knapsack_activity_categories.id"),
        nullable=False,
        index=True,
    )


class KnapsackActivityFunction(Base):
    __tablename__ = "knapsack_activity_functions"
    __table_args__ = (
        UniqueConstraint("name", name="uq_knapsack_activity_function_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)


class KnapsackRecordActivityFunction(Base):
    __tablename__ = "knapsack_record_activity_functions"
    __table_args__ = (
        UniqueConstraint(
            "knapsack_record_id",
            "function_id",
            name="uq_knapsack_record_activity_function",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knapsack_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knapsack_records.id"),
        nullable=False,
        index=True,
    )
    function_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knapsack_activity_functions.id"),
        nullable=False,
        index=True,
    )


class KnapsackTargetSpecies(Base):
    __tablename__ = "knapsack_target_species"
    __table_args__ = (
        UniqueConstraint("name", name="uq_knapsack_target_species_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)


class KnapsackRecordTargetSpecies(Base):
    __tablename__ = "knapsack_record_target_species"
    __table_args__ = (
        UniqueConstraint(
            "knapsack_record_id",
            "target_species_id",
            name="uq_knapsack_record_target_species",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knapsack_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knapsack_records.id"),
        nullable=False,
        index=True,
    )
    target_species_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knapsack_target_species.id"),
        nullable=False,
        index=True,
    )


class KnapsackRecordLink(Base):
    __tablename__ = "knapsack_record_links"
    __table_args__ = (
        UniqueConstraint(
            "knapsack_record_id",
            "link_type",
            "url",
            name="uq_knapsack_record_link",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knapsack_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("knapsack_records.id"),
        nullable=False,
        index=True,
    )
    link_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
