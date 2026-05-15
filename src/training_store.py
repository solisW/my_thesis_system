from __future__ import annotations

import pandas as pd

from .config import RAW_DATA_FILE
from .training_data_cleaner import rebuild_training_clean_table
from .training_data_generator import GeneratorConfig, generate_training_dataframe
from .training_repository import load_training_frame, replace_training_raw_data


def import_training_seed_data() -> None:
    if not load_training_frame("raw").empty:
        return
    if RAW_DATA_FILE.exists():
        frame = pd.read_csv(RAW_DATA_FILE)
    else:
        frame = generate_training_dataframe(GeneratorConfig())
    replace_training_raw_data(frame)
    rebuild_training_clean_table()


def replace_training_raw_data_with_frame(frame: pd.DataFrame) -> int:
    rows = replace_training_raw_data(frame)
    rebuild_training_clean_table()
    return rows


def rebuild_training_clean_data() -> int:
    return rebuild_training_clean_table()


__all__ = ["import_training_seed_data", "load_training_frame", "rebuild_training_clean_data", "replace_training_raw_data_with_frame"]
