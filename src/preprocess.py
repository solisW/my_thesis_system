from __future__ import annotations

import numpy as np
import pandas as pd

from .config import RAW_DATA_FILE
from .training_data_cleaner import build_windows, clean_training_dataframe, fit_scaler, transform_features


def load_dataset(csv_path: str | None = None) -> pd.DataFrame:
    path = csv_path or str(RAW_DATA_FILE)
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame.sort_values(["meter_id", "timestamp"], inplace=True)
    return frame


def clean_dataset(frame: pd.DataFrame) -> pd.DataFrame:
    return clean_training_dataframe(frame)


__all__ = [
    "build_windows",
    "clean_dataset",
    "fit_scaler",
    "load_dataset",
    "transform_features",
    "np",
]
