from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm import tqdm
from sqlalchemy import select
from sqlalchemy.orm import Session

from .tables.massbank_record import MassBankRecord
from .tables.massbank_peak_record import MassBankPeakRecord
from .tables.vocabulary import (
    FragmentationMode,
    IonMode,
    Ionization,
    InstrumentType,
    MSType,
    PrecursorType,
)


class MassBankImporter:
    """Importer for MassBank TSV and peak JSON files.

    This class is mainly intended for building or updating
    the initial SQLite database.

    Regular database access should be done using MassBankDatabase.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Record import
    # ------------------------------------------------------------------

    def import_records_tsv(
        self,
        tsv_path: str | Path,
    ) -> None:
        """Import MassBank record metadata from a TSV file."""
        df = pd.read_csv(tsv_path, sep="\t")
        self.import_records_dataframe(df)

    def import_records_dataframe(
        self,
        df: pd.DataFrame,
    ) -> None:
        """Import MassBank record metadata from a DataFrame.

        Existing records are updated by accession_id.
        New records are inserted.
        """
        if df.empty:
            return

        df = df.copy()

        if "identifier" not in df.columns:
            raise ValueError("records TSV must contain 'identifier' column.")

        self._insert_vocabularies(df)
        self.session.flush()

        for _, row in tqdm(df.iterrows(), total=df.size):
            accession_id = self._get_optional_str(row, "identifier")

            if accession_id is None:
                continue

            existing_record = self._get_existing_record(accession_id)

            if existing_record is None:
                record = MassBankRecord(
                    accession_id=accession_id,
                    name=self._get_optional_str(row, "name"),
                    smiles=self._get_optional_str(row, "smiles"),
                    inchikey=self._get_optional_str(row, "inchikey"),
                    formula=self._get_optional_str(row, "formula"),
                    precursor_mz=self._get_optional_float(row, "precursor_mz"),
                    precursor_type=self._get_optional_str(row, "precursor_type"),
                    splash=self._get_optional_str(row, "splash"),
                    ms_type=self._get_optional_str(row, "ms_type"),
                    ion_mode=self._get_optional_str(row, "ion_mode"),
                    collision_energy=self._get_optional_str(row, "collision_energy"),
                    retention_time=self._get_optional_str(row, "retention_time"),
                    ac_instrument=self._get_optional_str(row, "ac_instrument"),
                    instrument_type=self._get_optional_str(row, "instrument_type"),
                    ionization=self._get_optional_str(row, "ionization"),
                    ionization_voltage=self._get_optional_str(row, "ionization_voltage"),
                    fragmentation_mode=self._get_optional_str(row, "fragmentation_mode"),
                )
                self.session.add(record)

            else:
                self._update_record_from_row(existing_record, row)
                
        self.session.commit()

    def _get_existing_record(
        self,
        accession_id: str,
    ) -> MassBankRecord | None:
        """Get existing MassBankRecord by accession_id."""
        stmt = select(MassBankRecord).where(
            MassBankRecord.accession_id == accession_id
        )
        return self.session.scalar(stmt)

    def _get_existing_record_id(
        self,
        accession_id: str,
    ) -> int | None:
        """Get internal MassBankRecord.id by accession_id."""
        stmt = select(MassBankRecord.id).where(
            MassBankRecord.accession_id == accession_id
        )
        return self.session.scalar(stmt)

    def _update_record_from_row(
        self,
        record: MassBankRecord,
        row: pd.Series,
    ) -> None:
        """Update existing MassBankRecord from TSV row."""
        record.name = self._get_optional_str(row, "name")
        record.smiles = self._get_optional_str(row, "smiles")
        record.inchikey = self._get_optional_str(row, "inchikey")
        record.formula = self._get_optional_str(row, "formula")

        record.precursor_mz = self._get_optional_float(row, "precursor_mz")
        record.precursor_type = self._get_optional_str(row, "precursor_type")
        record.splash = self._get_optional_str(row, "splash")

        record.ms_type = self._get_optional_str(row, "ms_type")
        record.ion_mode = self._get_optional_str(row, "ion_mode")

        record.collision_energy = self._get_optional_str(row, "collision_energy")
        record.retention_time = self._get_optional_str(row, "retention_time")
        record.ac_instrument = self._get_optional_str(row, "ac_instrument")

        record.instrument_type = self._get_optional_str(row, "instrument_type")
        record.ionization = self._get_optional_str(row, "ionization")
        record.ionization_voltage = self._get_optional_str(row, "ionization_voltage")
        record.fragmentation_mode = self._get_optional_str(row, "fragmentation_mode")

    # ------------------------------------------------------------------
    # Peak import
    # ------------------------------------------------------------------

    def import_peaks_json(
        self,
        json_path: str | Path,
    ) -> None:
        """Import MassBank peak records from a JSON file."""
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.import_peaks_data(data)

    def import_peaks_data(
        self,
        data: list[dict[str, Any]],
    ) -> None:
        """Import peak records from loaded JSON data.

        Expected format
        ---------------
        [
            {
                "identifier": "MSBNK-HBM4EU-HB000111",
                "peaks": [
                    {
                        "mz": 60.0554,
                        "intensity": 349996.2,
                        "relative_intensity": 453.0,
                        "seq": 1
                    }
                ]
            }
        ]

        JSON identifier is resolved to MassBankRecord.id.
        Existing peaks are updated by massbank_record_id + peak_index.
        New peaks are inserted.
        """
        for record_data in tqdm(data):
            accession_id = record_data.get("identifier")

            if not accession_id:
                continue

            accession_id = str(accession_id)
            massbank_record_id = self._get_existing_record_id(accession_id)

            if massbank_record_id is None:
                continue

            peaks = record_data.get("peaks", [])

            for peak_index, peak in enumerate(peaks):
                existing_peak = self._get_existing_peak(
                    massbank_record_id=massbank_record_id,
                    peak_index=peak_index,
                )

                if existing_peak is None:
                    peak_record = MassBankPeakRecord(
                        massbank_record_id=massbank_record_id,
                        peak_index=peak_index,
                        seq=self._optional_int_from_value(peak.get("seq")),
                        mz=float(peak["mz"]),
                        intensity=float(peak["intensity"]),
                        relative_intensity=self._optional_float_from_value(
                            peak.get("relative_intensity")
                        ),
                    )
                    self.session.add(peak_record)

                else:
                    existing_peak.seq = self._optional_int_from_value(
                        peak.get("seq")
                    )
                    existing_peak.mz = float(peak["mz"])
                    existing_peak.intensity = float(peak["intensity"])
                    existing_peak.relative_intensity = self._optional_float_from_value(
                        peak.get("relative_intensity")
                    )

        self.session.commit()

    def _get_existing_peak(
        self,
        massbank_record_id: int,
        peak_index: int,
    ) -> MassBankPeakRecord | None:
        """Get existing peak by massbank_record_id and peak_index."""
        stmt = select(MassBankPeakRecord).where(
            MassBankPeakRecord.massbank_record_id == massbank_record_id,
            MassBankPeakRecord.peak_index == peak_index,
        )
        return self.session.scalar(stmt)

    # ------------------------------------------------------------------
    # Vocabulary import
    # ------------------------------------------------------------------

    def _insert_vocabularies(
        self,
        df: pd.DataFrame,
    ) -> None:
        """Insert lookup-table values before inserting MassBank records."""
        self._insert_vocabulary(df, PrecursorType, "precursor_type")
        self._insert_vocabulary(df, MSType, "ms_type")
        self._insert_vocabulary(df, IonMode, "ion_mode")
        self._insert_vocabulary(df, InstrumentType, "instrument_type")
        self._insert_vocabulary(df, Ionization, "ionization")
        self._insert_vocabulary(df, FragmentationMode, "fragmentation_mode")

    def _insert_vocabulary(
        self,
        df: pd.DataFrame,
        model: type,
        column_name: str,
    ) -> None:
        """Insert unique non-null values into one vocabulary table."""
        if column_name not in df.columns:
            return

        values = (
            df[column_name]
            .dropna()
            .astype(str)
            .map(str.strip)
        )

        values = [
            value
            for value in values.unique().tolist()
            if value != ""
        ]

        if not values:
            return

        column = getattr(model, column_name)

        existing_values = {
            row[0]
            for row in self.session.execute(
                select(column).where(column.in_(values))
            ).all()
        }

        new_objects = [
            model(**{column_name: value})
            for value in values
            if value not in existing_values
        ]

        self.session.add_all(new_objects)

    # ------------------------------------------------------------------
    # Value conversion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_optional_str(
        row: pd.Series,
        column_name: str,
    ) -> str | None:
        if column_name not in row:
            return None

        value = row[column_name]

        if pd.isna(value):
            return None

        value = str(value).strip()

        if value == "":
            return None

        return value

    @staticmethod
    def _get_optional_float(
        row: pd.Series,
        column_name: str,
    ) -> float | None:
        if column_name not in row:
            return None

        return MassBankImporter._optional_float_from_value(row[column_name])

    @staticmethod
    def _optional_float_from_value(
        value: Any,
    ) -> float | None:
        if value is None:
            return None

        if pd.isna(value):
            return None

        if str(value).strip() == "":
            return None

        return float(value)

    @staticmethod
    def _optional_int_from_value(
        value: Any,
    ) -> int | None:
        if value is None:
            return None

        if pd.isna(value):
            return None

        if str(value).strip() == "":
            return None

        return int(value)