from __future__ import annotations

import argparse
import json
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .config import (
    BATCH_SIZE,
    FEATURE_COLUMNS,
    HIDDEN_SIZE,
    LEARNING_RATE,
    META_FILE,
    MODEL_FILE,
    MODEL_REGISTRY_DIR,
    NUM_LAYERS,
    SCALER_FILE,
    TRAIN_EPOCHS,
    TRAIN_SPLIT,
    WINDOW_SIZE,
    ensure_directories,
)
from .model_registry import activate_model_bundle, active_model_metadata, stage_model_bundle, should_activate
from .model import LSTMAutoEncoder
from .training_data_cleaner import build_windows, fit_scaler, rebuild_training_clean_table, transform_features
from .training_data_generator import GeneratorConfig, generate_and_store_training_raw_data
from .training_repository import load_training_frame, training_counts, training_database_health


class ContinuousTrainingService:
    def __init__(
        self,
        app: Any,
        *,
        interval_seconds: int = 300,
        meter_count: int = 8,
        records_per_meter: int = 24 * 30,
        seed: int = 42,
        on_iteration_done: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.app = app
        self.interval_seconds = interval_seconds
        self.meter_count = meter_count
        self.records_per_meter = records_per_meter
        self.seed = seed
        self.on_iteration_done = on_iteration_done
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._run_index = 0
        self._last_started_at: str | None = None
        self._last_finished_at: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    def start(
        self,
        *,
        interval_seconds: int | None = None,
        meter_count: int | None = None,
        records_per_meter: int | None = None,
        seed: int | None = None,
    ) -> None:
        with self._lock:
            if interval_seconds not in (None, ""):
                self.interval_seconds = max(1, int(interval_seconds))
            if meter_count not in (None, ""):
                self.meter_count = max(1, int(meter_count))
            if records_per_meter not in (None, ""):
                self.records_per_meter = max(WINDOW_SIZE + 1, int(records_per_meter))
            if seed not in (None, ""):
                self.seed = int(seed)
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._thread and not self._thread.is_alive():
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.is_running(),
            "interval_seconds": self.interval_seconds,
            "meter_count": self.meter_count,
            "records_per_meter": self.records_per_meter,
            "seed": self.seed,
            "run_index": self._run_index,
            "last_started_at": self._last_started_at,
            "last_finished_at": self._last_finished_at,
            "last_result": self._last_result,
            "last_error": self._last_error,
        }

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._run_once()
            self._stop_event.wait(self.interval_seconds)

    def _run_once(self) -> None:
        self._run_index += 1
        self._last_started_at = datetime.now().isoformat()
        self._last_error = None
        config = GeneratorConfig(
            meter_count=self.meter_count,
            records_per_meter=self.records_per_meter,
            seed=self.seed + self._run_index - 1,
        )
        try:
            with self.app.app_context():
                result = run_training_pipeline(regenerate=True, reclean=True, config=config)
            self._last_result = result
            if self.on_iteration_done:
                self.on_iteration_done(result)
        except Exception:
            self._last_error = traceback.format_exc(limit=8)
        finally:
            self._last_finished_at = datetime.now().isoformat()


def generate_training_data(config: GeneratorConfig | None = None) -> int:
    return generate_and_store_training_raw_data(config=config, export_csv=True, append=True)


def clean_training_data() -> int:
    return rebuild_training_clean_table()


def train_model_from_clean_table() -> dict[str, float | int]:
    ensure_directories()
    frame = load_training_frame("clean")
    if frame.empty:
        raise ValueError("训练清洗数据表为空，请先生成并清洗训练数据。")

    scaler = fit_scaler(frame)
    transformed = transform_features(frame, scaler)
    windows, metadata = build_windows(transformed, WINDOW_SIZE)
    windows = np.asarray(windows, dtype=np.float32)

    if len(windows) == 0:
        raise ValueError("训练窗口为空，无法训练模型。")

    normal_indices = [idx for idx, item in enumerate(metadata) if item["window_has_anomaly"] == 0]
    if not normal_indices:
        raise ValueError("没有正常窗口样本，无法训练模型。")

    normal_windows = windows[normal_indices]
    split_index = max(1, int(len(normal_windows) * TRAIN_SPLIT))
    train_windows = normal_windows[:split_index]
    valid_windows = normal_windows[split_index:] if split_index < len(normal_windows) else normal_windows[:1]

    train_loader = DataLoader(TensorDataset(torch.tensor(train_windows, dtype=torch.float32)), batch_size=BATCH_SIZE, shuffle=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = LSTMAutoEncoder(input_size=len(FEATURE_COLUMNS), hidden_size=HIDDEN_SIZE, num_layers=NUM_LAYERS).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.MSELoss()

    last_loss = 0.0
    best_valid_loss = float("inf")
    best_epoch = 0
    best_state: dict[str, torch.Tensor] | None = None
    epochs_without_improvement = 0
    early_stopping_patience = 4
    loss_curve: list[dict[str, float | int]] = []
    for epoch in range(TRAIN_EPOCHS):
        model.train()
        epoch_loss = 0.0
        for (batch,) in train_loader:
            batch = batch.to(device)
            optimizer.zero_grad()
            reconstructed = model(batch)
            loss = criterion(reconstructed, batch)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
        last_loss = epoch_loss / max(1, len(train_loader))
        valid_loss = _validation_loss(model, valid_windows, device)
        loss_curve.append({"epoch": epoch + 1, "train_loss": float(last_loss), "valid_loss": float(valid_loss)})
        print(f"Epoch {epoch + 1}/{TRAIN_EPOCHS} - loss: {last_loss:.6f} - val_loss: {valid_loss:.6f}")

        if valid_loss < best_valid_loss - 1e-6:
            best_valid_loss = valid_loss
            best_epoch = epoch + 1
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= early_stopping_patience:
                print(f"Early stopping at epoch {epoch + 1}, best epoch: {best_epoch}")
                break

    if best_state is not None:
        model.load_state_dict({key: value.to(device) for key, value in best_state.items()})

    threshold = _compute_threshold(model, valid_windows, device)
    evaluation = _evaluate_candidate(model, windows, metadata, threshold, device)
    evaluation["final_loss"] = float(last_loss)
    evaluation["best_valid_loss"] = float(best_valid_loss)
    evaluation["best_epoch"] = float(best_epoch)

    model_id = f"model-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    meta = {
        "feature_columns": FEATURE_COLUMNS,
        "window_size": WINDOW_SIZE,
        "hidden_size": HIDDEN_SIZE,
        "num_layers": NUM_LAYERS,
        "threshold": float(threshold),
        "threshold_strategy": "validation_error_p92",
        "training_summary": {
            "train_windows": int(len(train_windows)),
            "valid_windows": int(len(valid_windows)),
            "raw_count": int(training_counts()["raw"]),
            "clean_count": int(training_counts()["clean"]),
            "epochs_ran": int(len(loss_curve)),
            "early_stopping_patience": int(early_stopping_patience),
        },
        "loss_curve": loss_curve,
        "evaluation": evaluation,
    }

    staging_dir = MODEL_REGISTRY_DIR / "_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    temp_model = staging_dir / f"{model_id}.pt"
    temp_scaler = staging_dir / f"{model_id}.pkl"
    torch.save(model.state_dict(), temp_model)
    joblib.dump(scaler, temp_scaler)
    bundle_meta = stage_model_bundle(model_id=model_id, model_file=temp_model, scaler_file=temp_scaler, meta=meta)
    if temp_model.exists():
        temp_model.unlink()
    if temp_scaler.exists():
        temp_scaler.unlink()

    current = active_model_metadata()
    activated, activation_reason = should_activate(bundle_meta, current)
    if activated:
        activate_model_bundle(bundle_meta, activation_reason=activation_reason)

    return {
        "model_id": model_id,
        "threshold": float(threshold),
        "train_windows": int(len(train_windows)),
        "valid_windows": int(len(valid_windows)),
        "final_loss": float(last_loss),
        "f1": float(evaluation["f1"]),
        "accuracy": float(evaluation["accuracy"]),
        "precision": float(evaluation["precision"]),
        "recall": float(evaluation["recall"]),
        "activated": bool(activated),
        "activation_reason": activation_reason,
    }


def run_training_pipeline(
    *,
    regenerate: bool = False,
    reclean: bool = False,
    config: GeneratorConfig | None = None,
) -> dict[str, object]:
    summary: dict[str, object] = {"steps": []}

    counts = training_counts()
    if regenerate or counts["raw"] == 0:
        raw_count = generate_training_data(config=config)
        summary["steps"].append({"step": "generate", "rows": raw_count})

    counts = training_counts()
    if reclean or regenerate or counts["clean"] == 0:
        clean_count = clean_training_data()
        summary["steps"].append({"step": "clean", "rows": clean_count})

    train_result = train_model_from_clean_table()
    summary["steps"].append({"step": "train", **train_result})
    summary["counts"] = training_counts()
    summary["database_health"] = training_database_health()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="训练数据生成、清洗与模型训练入口")
    parser.add_argument("--generate", action="store_true", help="只生成训练原始数据并写入训练原始数据表")
    parser.add_argument("--clean", action="store_true", help="只从训练原始数据表清洗并写入训练清洗数据表")
    parser.add_argument("--train", action="store_true", help="只使用训练清洗数据表训练模型")
    parser.add_argument("--all", action="store_true", help="按 生成 -> 清洗 -> 训练 全流程执行")
    parser.add_argument("--check-db", action="store_true", help="检查训练原始表和训练清洗表的数据完整性")
    parser.add_argument("--sync-db", action="store_true", help="从训练原始表重建训练清洗表，并输出完整性检查")
    parser.add_argument("--continuous", action="store_true", help="持续循环执行 生成 -> 清洗 -> 训练")
    parser.add_argument("--interval-seconds", type=int, default=300, help="持续训练模式下两轮训练之间的等待秒数")
    parser.add_argument("--meter-count", type=int, default=8, help="生成训练数据时的设备数量")
    parser.add_argument("--records-per-meter", type=int, default=24 * 30, help="每台设备的训练记录数")
    parser.add_argument("--seed", type=int, default=42, help="生成训练数据的随机种子")
    args = parser.parse_args()

    from .app import app

    config = GeneratorConfig(
        meter_count=args.meter_count,
        records_per_meter=args.records_per_meter,
        seed=args.seed,
    )

    with app.app_context():
        if args.check_db:
            print(json.dumps(training_database_health(), ensure_ascii=False, indent=2))
            return
        if args.sync_db:
            clean_count = clean_training_data()
            print(json.dumps({"clean_rows": clean_count, "database_health": training_database_health()}, ensure_ascii=False, indent=2))
            return
        if args.continuous:
            service = ContinuousTrainingService(
                app,
                interval_seconds=args.interval_seconds,
                meter_count=args.meter_count,
                records_per_meter=args.records_per_meter,
                seed=args.seed,
            )
            service.start()
            print(json.dumps({"continuous_training": service.status()}, ensure_ascii=False, indent=2))
            try:
                while service.is_running():
                    service._stop_event.wait(1)
            except KeyboardInterrupt:
                service.stop()
                print(json.dumps({"continuous_training": service.status()}, ensure_ascii=False, indent=2))
            return
        if args.all or not any([args.generate, args.clean, args.train]):
            print(json.dumps(run_training_pipeline(regenerate=True, reclean=True, config=config), ensure_ascii=False, indent=2))
            return
        if args.generate:
            print(json.dumps({"generated_rows": generate_training_data(config=config)}, ensure_ascii=False, indent=2))
        if args.clean:
            print(json.dumps({"clean_rows": clean_training_data()}, ensure_ascii=False, indent=2))
        if args.train:
            print(json.dumps(train_model_from_clean_table(), ensure_ascii=False, indent=2))


def _validation_loss(model: LSTMAutoEncoder, data: np.ndarray, device: torch.device) -> float:
    errors = _reconstruction_errors(model, data, device)
    return float(np.mean(errors))


def _compute_threshold(model: LSTMAutoEncoder, data: np.ndarray, device: torch.device) -> float:
    errors = _reconstruction_errors(model, data, device)
    return float(np.percentile(errors, 92))


def _reconstruction_errors(model: LSTMAutoEncoder, data: np.ndarray, device: torch.device) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        tensor = torch.tensor(data, dtype=torch.float32, device=device)
        reconstructed = model(tensor)
        errors = torch.mean((reconstructed - tensor) ** 2, dim=(1, 2)).detach().cpu().numpy()
    return errors


def _evaluate_candidate(
    model: LSTMAutoEncoder,
    windows: np.ndarray,
    metadata: list[dict[str, object]],
    threshold: float,
    device: torch.device,
) -> dict[str, float]:
    model.eval()
    with torch.no_grad():
        tensor = torch.tensor(windows, dtype=torch.float32, device=device)
        reconstructed = model(tensor)
        errors = torch.mean((reconstructed - tensor) ** 2, dim=(1, 2)).detach().cpu().numpy()

    truth = np.asarray([int(item["window_has_anomaly"]) for item in metadata], dtype=np.int32)
    predicted = (errors > threshold).astype(np.int32)
    tp = int(np.sum((predicted == 1) & (truth == 1)))
    tn = int(np.sum((predicted == 0) & (truth == 0)))
    fp = int(np.sum((predicted == 1) & (truth == 0)))
    fn = int(np.sum((predicted == 0) & (truth == 1)))

    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    accuracy = (tp + tn) / max(1, len(truth))
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "accuracy": float(accuracy),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "tp": float(tp),
        "tn": float(tn),
        "fp": float(fp),
        "fn": float(fn),
    }


if __name__ == "__main__":
    main()
