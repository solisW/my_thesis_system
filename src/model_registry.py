from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import has_app_context

from .config import ACTIVE_MODEL_META_FILE, META_FILE, MODEL_FILE, MODEL_REGISTRY_DIR, SCALER_FILE, ensure_directories
from .database import ModelMetadata, db


def active_model_metadata() -> dict[str, Any] | None:
    if not ACTIVE_MODEL_META_FILE.exists():
        return None
    return json.loads(ACTIVE_MODEL_META_FILE.read_text(encoding="utf-8"))


def active_model_version() -> str | None:
    meta = active_model_metadata()
    return str(meta.get("model_id")) if meta else None


def sync_active_model_metadata_to_db() -> None:
    meta = active_model_metadata()
    if meta is not None:
        _persist_model_metadata(meta, is_active=True, activation_reason="系统启动同步当前激活模型。")


def stage_model_bundle(
    *,
    model_id: str,
    model_file: Path,
    scaler_file: Path,
    meta: dict[str, Any],
) -> dict[str, Any]:
    ensure_directories()
    bundle_dir = MODEL_REGISTRY_DIR / model_id
    bundle_dir.mkdir(parents=True, exist_ok=True)

    staged_model = bundle_dir / "lstm_autoencoder.pt"
    staged_scaler = bundle_dir / "scaler.pkl"
    staged_meta = bundle_dir / "train_meta.json"
    staged_bundle_meta = bundle_dir / "bundle_meta.json"

    shutil.copy2(model_file, staged_model)
    shutil.copy2(scaler_file, staged_scaler)
    staged_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    bundle_meta = {
        "model_id": model_id,
        "created_at": datetime.now().isoformat(),
        "paths": {
            "model": str(staged_model),
            "scaler": str(staged_scaler),
            "meta": str(staged_meta),
        },
        **meta,
    }
    staged_bundle_meta.write_text(json.dumps(bundle_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _persist_model_metadata(bundle_meta, is_active=False)
    return bundle_meta


def activate_model_bundle(bundle_meta: dict[str, Any], activation_reason: str | None = None) -> dict[str, Any]:
    model_path = Path(bundle_meta["paths"]["model"])
    scaler_path = Path(bundle_meta["paths"]["scaler"])
    meta_path = Path(bundle_meta["paths"]["meta"])

    shutil.copy2(model_path, MODEL_FILE)
    shutil.copy2(scaler_path, SCALER_FILE)
    shutil.copy2(meta_path, META_FILE)
    ACTIVE_MODEL_META_FILE.write_text(json.dumps(bundle_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _persist_model_metadata(bundle_meta, is_active=True, activation_reason=activation_reason)
    return bundle_meta


def _persist_model_metadata(
    bundle_meta: dict[str, Any],
    *,
    is_active: bool,
    activation_reason: str | None = None,
) -> None:
    if not has_app_context():
        return

    model_id = str(bundle_meta["model_id"])
    paths = bundle_meta.get("paths", {})
    evaluation = bundle_meta.get("evaluation", {})
    training_summary = bundle_meta.get("training_summary", {})

    if is_active:
        ModelMetadata.query.update({"is_active": False}, synchronize_session=False)

    row = ModelMetadata.query.filter_by(model_id=model_id).first()
    if row is None:
        row = ModelMetadata(model_id=model_id)
        db.session.add(row)

    row.model_path = str(paths.get("model", ""))
    row.scaler_path = str(paths.get("scaler", ""))
    row.meta_path = str(paths.get("meta", ""))
    row.feature_columns = json.dumps(bundle_meta.get("feature_columns", []), ensure_ascii=False)
    row.window_size = int(bundle_meta.get("window_size", 0))
    row.hidden_size = int(bundle_meta.get("hidden_size", 0))
    row.num_layers = int(bundle_meta.get("num_layers", 0))
    row.threshold = float(bundle_meta.get("threshold", 0.0))
    row.threshold_strategy = str(bundle_meta.get("threshold_strategy", "")) or None
    row.accuracy = _optional_float(evaluation.get("accuracy"))
    row.precision_score = _optional_float(evaluation.get("precision"))
    row.recall_score = _optional_float(evaluation.get("recall"))
    row.f1_score = _optional_float(evaluation.get("f1"))
    row.final_loss = _optional_float(evaluation.get("final_loss"))
    row.train_windows = _optional_int(training_summary.get("train_windows"))
    row.valid_windows = _optional_int(training_summary.get("valid_windows"))
    row.raw_count = _optional_int(training_summary.get("raw_count"))
    row.clean_count = _optional_int(training_summary.get("clean_count"))
    row.is_active = bool(is_active)
    row.activation_reason = activation_reason or row.activation_reason
    if is_active:
        row.activated_at = datetime.now()
    db.session.commit()


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def should_activate(candidate: dict[str, Any], current: dict[str, Any] | None) -> tuple[bool, str]:
    if current is None:
        return True, "首个可用模型，直接激活。"

    candidate_eval = candidate.get("evaluation", {})
    current_eval = current.get("evaluation", {})
    candidate_f1 = float(candidate_eval.get("f1", 0.0))
    current_f1 = float(current_eval.get("f1", 0.0))
    candidate_acc = float(candidate_eval.get("accuracy", 0.0))
    current_acc = float(current_eval.get("accuracy", 0.0))
    candidate_loss = float(candidate_eval.get("final_loss", 999999.0))
    current_loss = float(current_eval.get("final_loss", 999999.0))

    if candidate_f1 > current_f1 + 1e-9:
        return True, "候选模型 F1 更高。"
    if abs(candidate_f1 - current_f1) <= 1e-9 and candidate_acc > current_acc + 1e-9:
        return True, "候选模型 F1 持平但准确率更高。"
    if abs(candidate_f1 - current_f1) <= 1e-9 and abs(candidate_acc - current_acc) <= 1e-9 and candidate_loss < current_loss:
        return True, "候选模型指标持平但训练损失更低。"
    return False, "候选模型未超过当前激活模型。"
