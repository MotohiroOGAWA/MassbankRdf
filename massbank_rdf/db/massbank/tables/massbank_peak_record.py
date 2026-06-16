from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .basetb import Base

if TYPE_CHECKING:
    from .massbank_record import MassBankRecord


class MassBankPeakRecord(Base):
    __tablename__ = "massbank_peak_records"

    massbank_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("massbank_records.id"),
        primary_key=True,
        nullable=False,
        index=True,
        comment="Internal MassBankRecord.id.",
    )

    peak_index: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        nullable=False,
        comment="Calculated peak index within a spectrum.",
    )

    seq: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Original peak sequence number from source data, if available.",
    )

    mz: Mapped[float] = mapped_column(Float, nullable=False)
    intensity: Mapped[float] = mapped_column(Float, nullable=False)

    relative_intensity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    massbank_record: Mapped["MassBankRecord"] = relationship(
        back_populates="peaks",
    )