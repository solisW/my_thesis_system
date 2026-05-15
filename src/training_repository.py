from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import text

from .config import FEATURE_COLUMNS
from .database import TrainingCleanDataRecord, TrainingRawDataRecord, db


TRAINING_COLUMNS = ["timestamp", "meter_id", *FEATURE_COLUMNS, "is_injected_anomaly"]


def load_training_frame(source: str = "clean") -> pd.DataFrame:
    if source not in {"raw", "clean"}:
        raise ValueError("source must be 'raw' or 'clean'")
    model = TrainingCleanDataRecord if source == "clean" else TrainingRawDataRecord
    rows = model.query.order_by(model.meter_id.asc(), model.timestamp.asc()).all()
    if not rows:
        return pd.DataFrame(columns=TRAINING_COLUMNS)

    frame = pd.DataFrame(
        [
            {
                "timestamp": row.timestamp,
                "meter_id": row.meter_id,
                "instant_flow": row.instant_flow,
                "cumulative_usage": row.cumulative_usage,
                "battery_voltage": row.battery_voltage,
                "signal_strength": row.signal_strength,
                "valve_state": row.valve_state,
                "temperature": row.temperature,
                "pressure": row.pressure,
                "is_injected_anomaly": int(bool(row.is_injected_anomaly)),
            }
            for row in rows
        ]
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame


def replace_training_raw_data(frame: pd.DataFrame) -> int:
    prepared = prepare_training_frame(frame)
    TrainingRawDataRecord.query.delete()
    db.session.bulk_insert_mappings(
        TrainingRawDataRecord,
        [_row_to_mapping(row, "imported_at") for row in prepared.itertuples(index=False)],
    )
    db.session.commit()
    return len(prepared)


def append_training_raw_data(frame: pd.DataFrame) -> int:
    prepared = prepare_training_frame(frame)
    if prepared.empty:
        return 0
    db.session.bulk_insert_mappings(
        TrainingRawDataRecord,
        [_row_to_mapping(row, "imported_at") for row in prepared.itertuples(index=False)],
    )
    db.session.commit()
    return len(prepared)


def replace_training_clean_data(frame: pd.DataFrame) -> int:
    prepared = prepare_training_frame(frame)
    TrainingCleanDataRecord.query.delete()
    db.session.bulk_insert_mappings(
        TrainingCleanDataRecord,
        [_row_to_mapping(row, "cleaned_at") for row in prepared.itertuples(index=False)],
    )
    db.session.commit()
    return len(prepared)


def latest_raw_timestamp() -> pd.Timestamp | None:
    value = db.session.execute(text("select max(timestamp) from training_raw_data_records")).scalar()
    return pd.to_datetime(value) if value is not None else None


def training_counts() -> dict[str, int]:
    return {
        "raw": TrainingRawDataRecord.query.count(),
        "clean": TrainingCleanDataRecord.query.count(),
    }


def training_database_health() -> dict[str, object]:
    raw_count = TrainingRawDataRecord.query.count()
    clean_count = TrainingCleanDataRecord.query.count()
    raw_meter_count = db.session.execute(text("select count(distinct meter_id) from training_raw_data_records")).scalar() or 0
    clean_meter_count = db.session.execute(text("select count(distinct meter_id) from training_clean_data_records")).scalar() or 0
    raw_duplicate_keys = _duplicate_meter_time_count("training_raw_data_records")
    clean_duplicate_keys = _duplicate_meter_time_count("training_clean_data_records")
    raw_null_cells = _null_cell_count("training_raw_data_records", imported=True)
    clean_null_cells = _null_cell_count("training_clean_data_records", imported=False)
    raw_range = _timestamp_range("training_raw_data_records")
    clean_range = _timestamp_range("training_clean_data_records")

    issues: list[str] = []
    if raw_count == 0:
        issues.append("training_raw_data_records is empty")
    if clean_count == 0:
        issues.append("training_clean_data_records is empty")
    if raw_count != clean_count:
        issues.append("raw and clean training row counts differ")
    if raw_meter_count != clean_meter_count:
        issues.append("raw and clean training meter counts differ")
    if raw_duplicate_keys:
        issues.append("raw training data has duplicate meter_id/timestamp rows")
    if clean_duplicate_keys:
        issues.append("clean training data has duplicate meter_id/timestamp rows")
    if raw_null_cells:
        issues.append("raw training data has null cells")
    if clean_null_cells:
        issues.append("clean training data has null cells")
    if raw_range != clean_range:
        issues.append("raw and clean training timestamp ranges differ")

    return {
        "ok": not issues,
        "issues": issues,
        "raw": {
            "rows": raw_count,
            "meters": raw_meter_count,
            "duplicate_meter_timestamp_rows": raw_duplicate_keys,
            "null_cells": raw_null_cells,
            "timestamp_range": raw_range,
        },
        "clean": {
            "rows": clean_count,
            "meters": clean_meter_count,
            "duplicate_meter_timestamp_rows": clean_duplicate_keys,
            "null_cells": clean_null_cells,
            "timestamp_range": clean_range,
        },
    }


def prepare_training_frame(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = frame.copy()
    prepared["timestamp"] = pd.to_datetime(prepared["timestamp"])
    prepared["meter_id"] = prepared["meter_id"].astype(str)
    if "is_injected_anomaly" not in prepared.columns:
        prepared["is_injected_anomaly"] = 0
    prepared["is_injected_anomaly"] = prepared["is_injected_anomaly"].fillna(0).astype(int)
    prepared = prepared[TRAINING_COLUMNS].sort_values(["meter_id", "timestamp"]).reset_index(drop=True)
    return prepared


def _row_to_mapping(row: object, time_field: str) -> dict[str, object]:
    timestamp = row.timestamp.to_pydatetime() if hasattr(row.timestamp, "to_pydatetime") else row.timestamp
    return {
        "timestamp": timestamp,
        "meter_id": str(row.meter_id),
        "instant_flow": float(row.instant_flow),
        "cumulative_usage": float(row.cumulative_usage),
        "battery_voltage": float(row.battery_voltage),
        "signal_strength": float(row.signal_strength),
        "valve_state": int(row.valve_state),
        "temperature": float(row.temperature),
        "pressure": float(row.pressure),
        "is_injected_anomaly": bool(row.is_injected_anomaly),
        time_field: datetime.now(),
    }


def _duplicate_meter_time_count(table_name: str) -> int:
    return int(
        db.session.execute(
            text(
                f"""
                select count(*)
                from (
                    select meter_id, timestamp, count(*) as row_count
                    from {table_name}
                    group by meter_id, timestamp
                    having count(*) > 1
                ) duplicated
                """
            )
        ).scalar()
        or 0
    )


def _null_cell_count(table_name: str, *, imported: bool) -> int:
    time_field = "imported_at" if imported else "cleaned_at"
    columns = [*TRAINING_COLUMNS, time_field]
    expressions = " + ".join(f"sum(case when {column} is null then 1 else 0 end)" for column in columns)
    return int(db.session.execute(text(f"select {expressions} from {table_name}")).scalar() or 0)


def _timestamp_range(table_name: str) -> dict[str, str | None]:
    row = db.session.execute(text(f"select min(timestamp), max(timestamp) from {table_name}")).first()
    return {
        "min": str(row[0]) if row and row[0] is not None else None,
        "max": str(row[1]) if row and row[1] is not None else None,
    }
