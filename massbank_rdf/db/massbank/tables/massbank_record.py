from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .basetb import Base

if TYPE_CHECKING:
    from .massbank_peak_record import MassBankPeakRecord
    from .vocabulary import (
        FragmentationMode,
        InstrumentType,
        IonMode,
        Ionization,
        MSType,
        PrecursorType,
    )


class MassBankRecord(Base):
    __tablename__ = "massbank_records"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    accession_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        unique=True,
        index=True,
    )

    name: Mapped[str | None] = mapped_column(String, nullable=True)
    smiles: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    inchikey: Mapped[str | None] = mapped_column(String(27), nullable=True, index=True)
    formula: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    precursor_mz: Mapped[float | None] = mapped_column(Float, nullable=True)

    precursor_type: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("precursor_types.precursor_type"),
        nullable=True,
    )

    splash: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        index=True,
    )

    ms_type: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("ms_types.ms_type"),
        nullable=True,
    )

    ion_mode: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("ion_modes.ion_mode"),
        nullable=True,
    )

    collision_energy: Mapped[str | None] = mapped_column(String, nullable=True)
    retention_time: Mapped[str | None] = mapped_column(String, nullable=True)

    ac_instrument: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    instrument_type: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("instrument_types.instrument_type"),
        nullable=True,
    )

    ionization: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("ionizations.ionization"),
        nullable=True,
    )

    ionization_voltage: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    fragmentation_mode: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("fragmentation_modes.fragmentation_mode"),
        nullable=True,
    )

    peaks: Mapped[list["MassBankPeakRecord"]] = relationship(
        back_populates="massbank_record",
        cascade="all, delete-orphan",
    )

    precursor_type_ref: Mapped["PrecursorType | None"] = relationship(
        back_populates="massbank_records",
    )

    ms_type_ref: Mapped["MSType | None"] = relationship(
        back_populates="massbank_records",
    )

    ion_mode_ref: Mapped["IonMode | None"] = relationship(
        back_populates="massbank_records",
    )

    instrument_type_ref: Mapped["InstrumentType | None"] = relationship(
        back_populates="massbank_records",
    )

    ionization_ref: Mapped["Ionization | None"] = relationship(
        back_populates="massbank_records",
    )

    fragmentation_mode_ref: Mapped["FragmentationMode | None"] = relationship(
        back_populates="massbank_records",
    )


from .massbank_peak_record import MassBankPeakRecord  # noqa: E402,F401
from .vocabulary import (  # noqa: E402,F401
    FragmentationMode,
    InstrumentType,
    IonMode,
    Ionization,
    MSType,
    PrecursorType,
)