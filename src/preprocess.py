from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from .config import FEATURE_COLUMNS, WINDOW_SIZE


def load_dataset(csv_path: str | None = None) -> pd.DataFrame:
    path = csv_path
    if path is None:
        from .config import RAW_DATA_FILE

        path = str(RAW_DATA_FILE)
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame.sort_values(["meter_id", "timestamp"], inplace=True)
    return frame


def clean_dataset(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame[FEATURE_COLUMNS] = frame[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)
    frame[FEATURE_COLUMNS] = frame.groupby("meter_id")[FEATURE_COLUMNS].transform(
        lambda x: x.interpolate(limit_direction="both").bfill().ffill()
    )
    frame[FEATURE_COLUMNS] = frame[FEATURE_COLUMNS].fillna(frame[FEATURE_COLUMNS].median(numeric_only=True))
    return frame


def fit_scaler(frame: pd.DataFrame) -> StandardScaler:
    scaler = StandardScaler()
    scaler.fit(frame[FEATURE_COLUMNS])
    return scaler


def transform_features(frame: pd.DataFrame, scaler: StandardScaler) -> pd.DataFrame:
    transformed = frame.copy()
    transformed[FEATURE_COLUMNS] = scaler.transform(transformed[FEATURE_COLUMNS])
    return transformed


def build_windows(frame: pd.DataFrame, window_size: int = WINDOW_SIZE) -> Tuple[np.ndarray, List[Dict[str, object]]]:
    windows: List[np.ndarray] = []
    metadata: List[Dict[str, object]] = []

    for meter_id, meter_frame in frame.groupby("meter_id"):
        meter_frame = meter_frame.sort_values("timestamp").reset_index(drop=True)
        feature_values = meter_frame[FEATURE_COLUMNS].to_numpy(dtype=np.float32)
        labels = (
            meter_frame["is_injected_anomaly"].to_numpy(dtype=np.int32)
            if "is_injected_anomaly" in meter_frame.columns
            else np.zeros(len(meter_frame), dtype=np.int32)
        )

        for index in range(len(meter_frame) - window_size + 1):
            window = feature_values[index : index + window_size]
            windows.append(window)
            metadata.append(
                {
                    "meter_id": meter_id,
                    "start_time": str(meter_frame.loc[index, "timestamp"]),
                    "end_time": str(meter_frame.loc[index + window_size - 1, "timestamp"]),
                    "window_has_anomaly": int(labels[index : index + window_size].max()),
                }
            )

    return np.asarray(windows, dtype=np.float32), metadata
