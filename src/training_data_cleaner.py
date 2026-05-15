from __future__ import annotations

import pandas as pd
from sklearn.preprocessing import StandardScaler

from .config import FEATURE_COLUMNS, WINDOW_SIZE
from .training_repository import load_training_frame, replace_training_clean_data


def clean_training_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    cleaned = frame.copy()
    if "is_injected_anomaly" not in cleaned.columns:
        cleaned["is_injected_anomaly"] = 0
    cleaned[FEATURE_COLUMNS] = cleaned[FEATURE_COLUMNS].replace([float("inf"), float("-inf")], pd.NA)
    cleaned[FEATURE_COLUMNS] = cleaned.groupby("meter_id")[FEATURE_COLUMNS].transform(
        lambda values: values.interpolate(limit_direction="both").bfill().ffill()
    )
    cleaned[FEATURE_COLUMNS] = cleaned[FEATURE_COLUMNS].fillna(cleaned[FEATURE_COLUMNS].median(numeric_only=True))
    cleaned["timestamp"] = pd.to_datetime(cleaned["timestamp"])
    cleaned["is_injected_anomaly"] = cleaned["is_injected_anomaly"].fillna(0).astype(int)
    return cleaned.sort_values(["meter_id", "timestamp"]).reset_index(drop=True)


def rebuild_training_clean_table() -> int:
    raw_frame = load_training_frame("raw")
    if raw_frame.empty:
        return replace_training_clean_data(raw_frame)
    cleaned = clean_training_dataframe(raw_frame)
    return replace_training_clean_data(cleaned)


def fit_scaler(frame: pd.DataFrame) -> StandardScaler:
    scaler = StandardScaler()
    scaler.fit(frame[FEATURE_COLUMNS])
    return scaler


def transform_features(frame: pd.DataFrame, scaler: StandardScaler) -> pd.DataFrame:
    transformed = frame.copy()
    transformed[FEATURE_COLUMNS] = scaler.transform(transformed[FEATURE_COLUMNS])
    return transformed


def build_windows(frame: pd.DataFrame, window_size: int = WINDOW_SIZE) -> tuple[list, list[dict[str, object]]]:
    windows = []
    metadata: list[dict[str, object]] = []

    for meter_id, meter_frame in frame.groupby("meter_id"):
        meter_frame = meter_frame.sort_values("timestamp").reset_index(drop=True)
        feature_values = meter_frame[FEATURE_COLUMNS].to_numpy(dtype="float32")
        labels = meter_frame["is_injected_anomaly"].to_numpy(dtype="int32")

        for index in range(len(meter_frame) - window_size + 1):
            windows.append(feature_values[index : index + window_size])
            metadata.append(
                {
                    "meter_id": meter_id,
                    "start_time": str(meter_frame.loc[index, "timestamp"]),
                    "end_time": str(meter_frame.loc[index + window_size - 1, "timestamp"]),
                    "window_has_anomaly": int(labels[index : index + window_size].max()),
                }
            )

    return windows, metadata
