import math
from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd

from .config import RAW_DATA_FILE, ensure_directories


@dataclass
class GeneratorConfig:
    meter_count: int = 8
    records_per_meter: int = 24 * 30
    seed: int = 42


def _inject_anomalies(frame: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    frame = frame.copy()
    anomaly_indices = rng.choice(frame.index, size=max(8, len(frame) // 20), replace=False)

    spike_group = anomaly_indices[: len(anomaly_indices) // 3]
    frame.loc[spike_group, "instant_flow"] *= rng.uniform(2.8, 4.5, size=len(spike_group))

    low_battery_group = anomaly_indices[len(anomaly_indices) // 3 : 2 * len(anomaly_indices) // 3]
    frame.loc[low_battery_group, "battery_voltage"] = rng.uniform(2.1, 2.7, size=len(low_battery_group))

    jump_group = anomaly_indices[2 * len(anomaly_indices) // 3 :]
    frame.loc[jump_group, "signal_strength"] = rng.uniform(5, 18, size=len(jump_group))
    frame.loc[jump_group, "cumulative_usage"] += rng.uniform(5, 15, size=len(jump_group))

    frame["is_injected_anomaly"] = 0
    frame.loc[anomaly_indices, "is_injected_anomaly"] = 1
    return frame


def build_dataset(config: GeneratorConfig) -> pd.DataFrame:
    rng = np.random.default_rng(config.seed)
    start_time = pd.Timestamp("2026-01-01 00:00:00")
    all_rows: List[pd.DataFrame] = []

    for meter_index in range(config.meter_count):
        timestamps = pd.date_range(start_time, periods=config.records_per_meter, freq="h")
        base_load = rng.uniform(0.08, 0.2)
        hours = np.arange(config.records_per_meter)

        daily_pattern = np.sin(2 * math.pi * (hours % 24) / 24 - 0.7) + 1.3
        weekly_pattern = np.where((hours // 24) % 7 >= 5, 0.85, 1.0)
        instant_flow = np.clip(
            base_load * daily_pattern * weekly_pattern + rng.normal(0, 0.025, config.records_per_meter),
            0,
            None,
        )
        cumulative_usage = np.cumsum(instant_flow)

        frame = pd.DataFrame(
            {
                "timestamp": timestamps,
                "meter_id": f"GM{meter_index + 1:03d}",
                "instant_flow": instant_flow,
                "cumulative_usage": cumulative_usage,
                "battery_voltage": rng.normal(3.45, 0.05, config.records_per_meter),
                "signal_strength": np.clip(rng.normal(78, 6, config.records_per_meter), 20, 100),
                "valve_state": rng.choice([0, 1], p=[0.04, 0.96], size=config.records_per_meter),
                "temperature": rng.normal(18, 6, config.records_per_meter),
                "pressure": rng.normal(2.1, 0.18, config.records_per_meter),
            }
        )

        if meter_index % 2 == 0:
            frame = _inject_anomalies(frame, rng)
        else:
            frame["is_injected_anomaly"] = 0

        all_rows.append(frame)

    dataset = pd.concat(all_rows, ignore_index=True)
    dataset.sort_values(["meter_id", "timestamp"], inplace=True)
    return dataset


def main() -> None:
    ensure_directories()
    dataset = build_dataset(GeneratorConfig())
    dataset.to_csv(RAW_DATA_FILE, index=False, encoding="utf-8-sig")
    print(f"数据已生成: {RAW_DATA_FILE}")
    print(f"样本数量: {len(dataset)}")


if __name__ == "__main__":
    main()
