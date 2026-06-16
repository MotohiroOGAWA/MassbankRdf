from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .basetb import Base


class PrecursorType(Base):
    __tablename__ = "precursor_types"

    precursor_type: Mapped[str] = mapped_column(String, primary_key=True)

    massbank_records: Mapped[list["MassBankRecord"]] = relationship(
        back_populates="precursor_type_ref",
    )


class MSType(Base):
    __tablename__ = "ms_types"

    ms_type: Mapped[str] = mapped_column(String, primary_key=True)

    massbank_records: Mapped[list["MassBankRecord"]] = relationship(
        back_populates="ms_type_ref",
    )


class IonMode(Base):
    __tablename__ = "ion_modes"

    ion_mode: Mapped[str] = mapped_column(String, primary_key=True)

    massbank_records: Mapped[list["MassBankRecord"]] = relationship(
        back_populates="ion_mode_ref",
    )


class InstrumentType(Base):
    __tablename__ = "instrument_types"

    instrument_type: Mapped[str] = mapped_column(String, primary_key=True)

    massbank_records: Mapped[list["MassBankRecord"]] = relationship(
        back_populates="instrument_type_ref",
    )


class Ionization(Base):
    __tablename__ = "ionizations"

    ionization: Mapped[str] = mapped_column(String, primary_key=True)

    massbank_records: Mapped[list["MassBankRecord"]] = relationship(
        back_populates="ionization_ref",
    )


class FragmentationMode(Base):
    __tablename__ = "fragmentation_modes"

    fragmentation_mode: Mapped[str] = mapped_column(String, primary_key=True)

    massbank_records: Mapped[list["MassBankRecord"]] = relationship(
        back_populates="fragmentation_mode_ref",
    )


from .massbank_record import MassBankRecord  # noqa: E402,F401
