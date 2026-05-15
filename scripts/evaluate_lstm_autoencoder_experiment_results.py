from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import auc, roc_curve


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app import app
from src.config import FEATURE_COLUMNS, META_FILE, MODEL_FILE, SCALER_FILE, WINDOW_SIZE
from src.model import LSTMAutoEncoder
from src.model_registry import active_model_metadata
from src.training_data_cleaner import build_windows, transform_features
from src.training_repository import load_training_frame


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "experiment_results"
TRADITIONAL_FEATURES = ["instant_flow", "battery_voltage", "signal_strength", "pressure", "temperature"]


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 LSTM AutoEncoder 异常检测实验评估图表与数据。")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="实验结果输出目录")
    parser.add_argument("--source", choices=["clean", "raw"], default="clean", help="评估所用训练数据表")
    parser.add_argument("--max-windows", type=int, default=0, help="最多评估的窗口数量，0 表示不限制")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with app.app_context():
        meta = _load_model_meta()
        frame = load_training_frame(args.source)

    if frame.empty:
        raise SystemExit("训练数据表为空，请先运行 start_system.bat，并在系统设置页开启持续训练生成训练数据。")

    model, scaler, model_meta = _load_model(meta)
    transformed = transform_features(frame, scaler)
    windows, metadata = build_windows(transformed, window_size=int(model_meta.get("window_size", WINDOW_SIZE)))
    raw_windows, _ = build_windows(frame, window_size=int(model_meta.get("window_size", WINDOW_SIZE)))
    if not windows:
        raise SystemExit("可评估窗口数量不足，请增加训练数据。")

    windows_np = np.asarray(windows, dtype=np.float32)
    raw_windows_np = np.asarray(raw_windows, dtype=np.float32)
    labels = np.asarray([int(item["window_has_anomaly"]) for item in metadata], dtype=np.int32)
    if args.max_windows and args.max_windows > 0:
        windows_np = windows_np[: args.max_windows]
        raw_windows_np = raw_windows_np[: args.max_windows]
        labels = labels[: args.max_windows]
        metadata = metadata[: args.max_windows]

    reconstructed, ae_scores = _reconstruct(model, windows_np)
    online_threshold = float(model_meta.get("threshold", np.percentile(ae_scores, 92)))
    threshold_rows = _threshold_scan_rows(labels, ae_scores)
    experiment_threshold = _best_threshold(threshold_rows)
    ae_predicted = (ae_scores > experiment_threshold).astype(np.int32)

    fixed_predicted = _fixed_threshold_predict(raw_windows_np)
    sigma_predicted = _three_sigma_predict(frame, raw_windows_np)

    method_rows = [
        _metrics_row("LSTM AutoEncoder（优化阈值）", labels, ae_predicted),
        _metrics_row("固定阈值法", labels, fixed_predicted),
        _metrics_row("3-Sigma 统计法", labels, sigma_predicted),
    ]

    fpr, tpr, auc_value, roc_rows = _roc_rows(labels, ae_scores)
    case = _select_case(labels, ae_scores, reconstructed, windows_np, raw_windows_np, metadata, online_threshold, scaler)
    normal_case = _select_normal_case(labels, ae_scores, reconstructed, windows_np, raw_windows_np, metadata, online_threshold, scaler)
    distribution_rows = _error_distribution_rows(labels, ae_scores)
    error_score_rows = _error_score_rows(case, online_threshold)
    loss_rows = _loss_rows(model_meta)

    _write_csv(output_dir / "method_comparison.csv", method_rows)
    _write_csv(output_dir / "roc_curve.csv", roc_rows)
    _write_csv(output_dir / "threshold_f1_curve.csv", threshold_rows)
    _write_csv(output_dir / "loss_curve.csv", loss_rows)
    _write_csv(output_dir / "reconstruction_case.csv", case["rows"])
    _write_csv(output_dir / "normal_reconstruction_case.csv", normal_case["rows"])
    _write_csv(output_dir / "anomaly_error_score_curve.csv", error_score_rows)
    _write_csv(output_dir / "reconstruction_error_distribution.csv", distribution_rows)

    _write_loss_svg(output_dir / "loss_curve.svg", loss_rows)
    _write_roc_svg(output_dir / "roc_auc_curve.svg", fpr, tpr, auc_value)
    _write_threshold_svg(output_dir / "threshold_f1_curve.svg", threshold_rows)
    _write_comparison_svg(output_dir / "method_comparison.svg", method_rows)
    _write_reconstruction_svg(output_dir / "reconstruction_case.svg", case, online_threshold)
    _write_reconstruction_curve_svg(output_dir / "normal_reconstruction_case.svg", normal_case, "正常样本重构结果")
    _write_error_score_svg(output_dir / "anomaly_error_score_curve.svg", case, online_threshold)
    _write_error_distribution_svg(output_dir / "reconstruction_error_distribution.svg", distribution_rows, online_threshold)

    summary = {
        "model_id": meta.get("model_id"),
        "online_threshold": online_threshold,
        "experiment_threshold": experiment_threshold,
        "window_size": int(model_meta.get("window_size", WINDOW_SIZE)),
        "feature_columns": FEATURE_COLUMNS,
        "sample_windows": int(len(labels)),
        "positive_windows": int(labels.sum()),
        "negative_windows": int(len(labels) - labels.sum()),
        "auc": auc_value,
        "outputs": {
            "loss_curve": "loss_curve.svg",
            "roc_auc_curve": "roc_auc_curve.svg",
            "threshold_f1_curve": "threshold_f1_curve.svg",
            "method_comparison": "method_comparison.csv",
            "method_comparison_chart": "method_comparison.svg",
            "reconstruction_case": "reconstruction_case.svg",
            "normal_reconstruction_case": "normal_reconstruction_case.svg",
            "anomaly_error_score_curve": "anomaly_error_score_curve.svg",
            "reconstruction_error_distribution": "reconstruction_error_distribution.svg",
        },
    }
    (output_dir / "experiment_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "output_dir": str(output_dir), **summary}, ensure_ascii=False, indent=2))


def _load_model_meta() -> dict[str, Any]:
    meta = active_model_metadata()
    if meta is not None:
        return meta
    if META_FILE.exists():
        raw = json.loads(META_FILE.read_text(encoding="utf-8"))
        raw.setdefault("paths", {"model": str(MODEL_FILE), "scaler": str(SCALER_FILE), "meta": str(META_FILE)})
        raw.setdefault("model_id", "active-model")
        return raw
    raise SystemExit("未找到激活模型元数据，请先运行 start_system.bat，并在系统设置页开启持续训练。")


def _load_model(meta: dict[str, Any]) -> tuple[LSTMAutoEncoder, Any, dict[str, Any]]:
    paths = meta.get("paths", {})
    model_path = Path(paths.get("model") or MODEL_FILE)
    scaler_path = Path(paths.get("scaler") or SCALER_FILE)
    meta_path = Path(paths.get("meta") or META_FILE)
    if not model_path.exists() and MODEL_FILE.exists():
        model_path = MODEL_FILE
    if not scaler_path.exists() and SCALER_FILE.exists():
        scaler_path = SCALER_FILE
    if not meta_path.exists() and META_FILE.exists():
        meta_path = META_FILE
    if not model_path.exists() or not scaler_path.exists():
        raise SystemExit("模型文件或 Scaler 文件不存在，请先运行 start_system.bat，并在系统设置页开启持续训练。")

    model_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else meta
    hidden_size = int(model_meta.get("hidden_size", meta.get("hidden_size", 32)))
    num_layers = int(model_meta.get("num_layers", meta.get("num_layers", 2)))
    model = LSTMAutoEncoder(input_size=len(FEATURE_COLUMNS), hidden_size=hidden_size, num_layers=num_layers)
    model.load_state_dict(torch.load(model_path, map_location="cpu"))
    model.eval()
    scaler = joblib.load(scaler_path)
    return model, scaler, model_meta


def _reconstruct(model: LSTMAutoEncoder, windows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    with torch.no_grad():
        tensor = torch.tensor(windows, dtype=torch.float32)
        reconstructed = model(tensor).detach().cpu().numpy()
    scores = np.mean((reconstructed - windows) ** 2, axis=(1, 2))
    return reconstructed, scores


def _fixed_threshold_predict(raw_windows: np.ndarray) -> np.ndarray:
    feature_index = {name: index for index, name in enumerate(FEATURE_COLUMNS)}
    flow = raw_windows[:, :, feature_index["instant_flow"]]
    battery = raw_windows[:, :, feature_index["battery_voltage"]]
    signal = raw_windows[:, :, feature_index["signal_strength"]]
    pressure = raw_windows[:, :, feature_index["pressure"]]
    return (
        (flow.max(axis=1) > 1.6)
        | (battery.min(axis=1) < 2.45)
        | (signal.min(axis=1) < 18)
        | (pressure.max(axis=1) > 2.8)
        | (pressure.min(axis=1) < 1.4)
    ).astype(np.int32)


def _three_sigma_predict(frame: pd.DataFrame, raw_windows: np.ndarray) -> np.ndarray:
    normal = frame[frame["is_injected_anomaly"].astype(int) == 0]
    base = normal if not normal.empty else frame
    means = base[TRADITIONAL_FEATURES].mean()
    stds = base[TRADITIONAL_FEATURES].std().replace(0, np.nan).fillna(1.0)
    feature_index = [FEATURE_COLUMNS.index(name) for name in TRADITIONAL_FEATURES]
    values = raw_windows[:, :, feature_index]
    mean_values = means.to_numpy(dtype=np.float32)
    std_values = stds.to_numpy(dtype=np.float32)
    z_scores = np.abs((values - mean_values) / std_values)
    return (z_scores.max(axis=(1, 2)) > 3.0).astype(np.int32)


def _metrics_row(method: str, truth: np.ndarray, predicted: np.ndarray) -> dict[str, Any]:
    tp = int(np.sum((predicted == 1) & (truth == 1)))
    tn = int(np.sum((predicted == 0) & (truth == 0)))
    fp = int(np.sum((predicted == 1) & (truth == 0)))
    fn = int(np.sum((predicted == 0) & (truth == 1)))
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    accuracy = (tp + tn) / max(1, len(truth))
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    return {
        "method": method,
        "accuracy": round(float(accuracy), 6),
        "precision": round(float(precision), 6),
        "recall": round(float(recall), 6),
        "f1": round(float(f1), 6),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    }


def _roc_rows(truth: np.ndarray, scores: np.ndarray) -> tuple[np.ndarray, np.ndarray, float | None, list[dict[str, Any]]]:
    if len(np.unique(truth)) < 2:
        return np.asarray([0, 1]), np.asarray([0, 1]), None, [
            {"fpr": 0.0, "tpr": 0.0, "threshold": ""},
            {"fpr": 1.0, "tpr": 1.0, "threshold": ""},
        ]
    fpr, tpr, thresholds = roc_curve(truth, scores)
    auc_value = float(auc(fpr, tpr))
    rows = [
        {
            "fpr": round(float(x), 8),
            "tpr": round(float(y), 8),
            "threshold": "" if math.isinf(float(threshold)) else round(float(threshold), 8),
        }
        for x, y, threshold in zip(fpr, tpr, thresholds)
    ]
    return fpr, tpr, auc_value, rows


def _threshold_scan_rows(truth: np.ndarray, scores: np.ndarray) -> list[dict[str, Any]]:
    thresholds = np.linspace(float(scores.min()), float(scores.max()), num=80)
    rows = []
    for threshold in thresholds:
        predicted = (scores > threshold).astype(np.int32)
        row = _metrics_row("LSTM AutoEncoder", truth, predicted)
        rows.append(
            {
                "threshold": round(float(threshold), 8),
                "precision": row["precision"],
                "recall": row["recall"],
                "f1": row["f1"],
                "accuracy": row["accuracy"],
            }
        )
    return rows


def _best_threshold(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    best = max(rows, key=lambda item: (float(item["f1"]), float(item["recall"]), float(item["precision"])))
    return float(best["threshold"])


def _select_case(
    truth: np.ndarray,
    scores: np.ndarray,
    reconstructed: np.ndarray,
    windows: np.ndarray,
    raw_windows: np.ndarray,
    metadata: list[dict[str, object]],
    threshold: float,
    scaler: Any,
) -> dict[str, Any]:
    candidates = np.where((truth == 1) & (scores > threshold))[0]
    if len(candidates) == 0:
        candidates = np.where(truth == 1)[0]
    if len(candidates) == 0:
        candidates = np.asarray([int(np.argmax(scores))])
    index = int(candidates[np.argmax(scores[candidates])])

    errors = np.mean((reconstructed[index] - windows[index]) ** 2, axis=1)
    reconstructed_raw = scaler.inverse_transform(reconstructed[index])
    flow_feature_index = FEATURE_COLUMNS.index("instant_flow")
    rows = [
        {
            "step": step + 1,
            "original_flow": round(float(raw_windows[index, step, flow_feature_index]), 6),
            "reconstructed_flow": round(float(reconstructed_raw[step, flow_feature_index]), 6),
            "error": round(float(errors[step]), 8),
        }
        for step in range(raw_windows.shape[1])
    ]
    return {
        "index": index,
        "score": float(scores[index]),
        "label": int(truth[index]),
        "metadata": metadata[index],
        "rows": rows,
    }


def _select_normal_case(
    truth: np.ndarray,
    scores: np.ndarray,
    reconstructed: np.ndarray,
    windows: np.ndarray,
    raw_windows: np.ndarray,
    metadata: list[dict[str, object]],
    threshold: float,
    scaler: Any,
) -> dict[str, Any]:
    candidates = np.where((truth == 0) & (scores <= threshold))[0]
    if len(candidates) == 0:
        candidates = np.where(truth == 0)[0]
    if len(candidates) == 0:
        candidates = np.asarray([int(np.argmin(scores))])
    index = int(candidates[np.argmin(scores[candidates])])

    errors = np.mean((reconstructed[index] - windows[index]) ** 2, axis=1)
    reconstructed_raw = scaler.inverse_transform(reconstructed[index])
    flow_feature_index = FEATURE_COLUMNS.index("instant_flow")
    rows = [
        {
            "step": step + 1,
            "original_flow": round(float(raw_windows[index, step, flow_feature_index]), 6),
            "reconstructed_flow": round(float(reconstructed_raw[step, flow_feature_index]), 6),
            "error": round(float(errors[step]), 8),
        }
        for step in range(raw_windows.shape[1])
    ]
    return {
        "index": index,
        "score": float(scores[index]),
        "label": int(truth[index]),
        "metadata": metadata[index],
        "rows": rows,
    }


def _error_score_rows(case: dict[str, Any], threshold: float) -> list[dict[str, Any]]:
    return [
        {
            "step": row["step"],
            "error": row["error"],
            "threshold": round(float(threshold), 8),
        }
        for row in case["rows"]
    ]


def _error_distribution_rows(truth: np.ndarray, scores: np.ndarray, bins: int = 24) -> list[dict[str, Any]]:
    min_score = float(scores.min())
    max_score = float(np.percentile(scores, 99.5))
    real_max_score = float(scores.max())
    if abs(max_score - min_score) < 1e-12:
        min_score -= 0.5
        max_score += 0.5
    edges = np.linspace(min_score, max_score, num=bins + 1)
    rows: list[dict[str, Any]] = []
    for index in range(bins):
        left = edges[index]
        right = edges[index + 1]
        if index == bins - 1:
            mask = scores >= left
        else:
            mask = (scores >= left) & (scores < right)
        normal_count = int(np.sum(mask & (truth == 0)))
        anomaly_count = int(np.sum(mask & (truth == 1)))
        rows.append(
            {
                "bin_start": round(float(left), 8),
                "bin_end": round(float(right), 8),
                "bin_mid": round(float((left + right) / 2), 8),
                "normal_count": normal_count,
                "anomaly_count": anomaly_count,
                "contains_tail": index == bins - 1 and real_max_score > max_score,
            }
        )
    return rows


def _loss_rows(model_meta: dict[str, Any]) -> list[dict[str, Any]]:
    loss_curve = model_meta.get("loss_curve") or []
    if loss_curve:
        return [
            {
                "epoch": int(item.get("epoch", index + 1)),
                "train_loss": float(item.get("train_loss", 0.0)),
                "valid_loss": float(item.get("valid_loss", 0.0)),
            }
            for index, item in enumerate(loss_curve)
        ]
    final_loss = float(model_meta.get("evaluation", {}).get("final_loss", 0.0))
    return [{"epoch": 1, "train_loss": final_loss, "valid_loss": final_loss}]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_loss_svg(path: Path, rows: list[dict[str, Any]]) -> None:
    x = [row["epoch"] for row in rows]
    train = [row["train_loss"] for row in rows]
    valid = [row["valid_loss"] for row in rows]
    series = [("训练 Loss", x, train, "#2563eb"), ("验证 Loss", x, valid, "#dc2626")]
    _write_line_svg(path, "训练过程收敛曲线", "Epoch", "MSE Loss", series)


def _write_roc_svg(path: Path, fpr: np.ndarray, tpr: np.ndarray, auc_value: float | None) -> None:
    title = "ROC 曲线" if auc_value is None else f"ROC 曲线 AUC={auc_value:.4f}"
    series = [("LSTM AutoEncoder", list(fpr), list(tpr), "#2563eb"), ("随机分类参考", [0, 1], [0, 1], "#9ca3af")]
    _write_line_svg(path, title, "False Positive Rate", "True Positive Rate", series, x_range=(0, 1), y_range=(0, 1))


def _write_threshold_svg(path: Path, rows: list[dict[str, Any]]) -> None:
    x = [row["threshold"] for row in rows]
    f1 = [row["f1"] for row in rows]
    precision = [row["precision"] for row in rows]
    recall = [row["recall"] for row in rows]
    series = [("F1-score", x, f1, "#16a34a"), ("Precision", x, precision, "#2563eb"), ("Recall", x, recall, "#dc2626")]
    _write_line_svg(path, "不同阈值下检测指标变化", "重构误差阈值", "Score", series, y_range=(0, 1))


def _write_comparison_svg(path: Path, rows: list[dict[str, Any]]) -> None:
    width, height = 920, 460
    margin = {"left": 70, "right": 30, "top": 70, "bottom": 80}
    metrics = ["accuracy", "precision", "recall", "f1"]
    colors = {"accuracy": "#2563eb", "precision": "#16a34a", "recall": "#dc2626", "f1": "#7c3aed"}
    chart_w = width - margin["left"] - margin["right"]
    chart_h = height - margin["top"] - margin["bottom"]
    group_w = chart_w / max(1, len(rows))
    bar_w = group_w / (len(metrics) + 1)
    parts = [_svg_header(width, height), _svg_text(width / 2, 32, "不同异常检测方法性能对比", size=22, weight="700", anchor="middle")]
    parts.append(_axis(margin, width, height))
    for i in range(6):
        y = margin["top"] + chart_h - chart_h * i / 5
        value = i / 5
        parts.append(f'<line x1="{margin["left"]}" y1="{y:.2f}" x2="{width - margin["right"]}" y2="{y:.2f}" stroke="#e5e7eb"/>')
        parts.append(_svg_text(margin["left"] - 10, y + 4, f"{value:.1f}", size=11, anchor="end"))
    for row_index, row in enumerate(rows):
        base_x = margin["left"] + row_index * group_w + bar_w * 0.5
        for metric_index, metric in enumerate(metrics):
            value = float(row[metric])
            h = chart_h * value
            x = base_x + metric_index * bar_w
            y = margin["top"] + chart_h - h
            parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w * 0.75:.2f}" height="{h:.2f}" fill="{colors[metric]}"/>')
        parts.append(_svg_text(base_x + bar_w * 1.8, height - 42, row["method"], size=12, anchor="middle"))
    legend_x = margin["left"]
    for index, metric in enumerate(metrics):
        x = legend_x + index * 150
        parts.append(f'<rect x="{x}" y="48" width="12" height="12" fill="{colors[metric]}"/>')
        parts.append(_svg_text(x + 18, 59, metric, size=12))
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _write_reconstruction_svg(path: Path, case: dict[str, Any], threshold: float) -> None:
    rows = case["rows"]
    steps = [row["step"] for row in rows]
    original = [row["original_flow"] for row in rows]
    reconstructed = [row["reconstructed_flow"] for row in rows]
    series = [
        ("原始流量", steps, original, "#2563eb"),
        ("重构流量", steps, reconstructed, "#16a34a"),
    ]
    title = f"典型异常样本重构分析 score={case['score']:.4f}"
    _write_line_svg(path, title, "时间步", "瞬时流量", series)


def _write_reconstruction_curve_svg(path: Path, case: dict[str, Any], title: str) -> None:
    rows = case["rows"]
    steps = [row["step"] for row in rows]
    original = [row["original_flow"] for row in rows]
    reconstructed = [row["reconstructed_flow"] for row in rows]
    series = [
        ("原始流量", steps, original, "#2563eb"),
        ("模型重构流量", steps, reconstructed, "#16a34a"),
    ]
    _write_line_svg(path, f"{title} score={case['score']:.4f}", "时间步", "瞬时流量", series)


def _write_error_score_svg(path: Path, case: dict[str, Any], threshold: float) -> None:
    rows = case["rows"]
    steps = [row["step"] for row in rows]
    errors = [row["error"] for row in rows]
    threshold_line = [threshold for _ in rows]
    series = [
        ("重构误差得分", steps, errors, "#dc2626"),
        ("模型阈值", steps, threshold_line, "#7c3aed"),
    ]
    _write_line_svg(path, f"异常样本重构误差得分曲线 score={case['score']:.4f}", "时间步", "MSE误差", series)


def _write_error_distribution_svg(path: Path, rows: list[dict[str, Any]], threshold: float) -> None:
    width, height = 920, 460
    margin = {"left": 72, "right": 36, "top": 78, "bottom": 72}
    chart_w = width - margin["left"] - margin["right"]
    chart_h = height - margin["top"] - margin["bottom"]
    max_count = max([int(row["normal_count"]) + int(row["anomaly_count"]) for row in rows] + [1])
    min_score = float(rows[0]["bin_start"]) if rows else 0.0
    max_score = float(rows[-1]["bin_end"]) if rows else 1.0
    group_w = chart_w / max(1, len(rows))
    bar_w = group_w * 0.34

    def sx(value: float) -> float:
        return margin["left"] + (value - min_score) / max(1e-12, max_score - min_score) * chart_w

    parts = [_svg_header(width, height), _svg_text(width / 2, 32, "重构误差分布图", size=22, weight="700", anchor="middle")]
    parts.append(_axis(margin, width, height))
    for i in range(6):
        y = margin["top"] + chart_h - chart_h * i / 5
        value = max_count * i / 5
        parts.append(f'<line x1="{margin["left"]}" y1="{y:.2f}" x2="{width - margin["right"]}" y2="{y:.2f}" stroke="#e5e7eb"/>')
        parts.append(_svg_text(margin["left"] - 10, y + 4, f"{value:.0f}", size=11, anchor="end"))

    for index, row in enumerate(rows):
        base_x = margin["left"] + index * group_w + group_w * 0.16
        normal_h = chart_h * int(row["normal_count"]) / max_count
        anomaly_h = chart_h * int(row["anomaly_count"]) / max_count
        normal_y = margin["top"] + chart_h - normal_h
        anomaly_y = margin["top"] + chart_h - anomaly_h
        parts.append(f'<rect x="{base_x:.2f}" y="{normal_y:.2f}" width="{bar_w:.2f}" height="{normal_h:.2f}" fill="#2563eb"/>')
        parts.append(f'<rect x="{base_x + bar_w + 2:.2f}" y="{anomaly_y:.2f}" width="{bar_w:.2f}" height="{anomaly_h:.2f}" fill="#dc2626"/>')
        if index % max(1, len(rows) // 6) == 0:
            parts.append(_svg_text(base_x + bar_w, height - 45, f"{float(row['bin_mid']):.3g}", size=10, anchor="middle"))

    threshold_x = sx(float(threshold))
    if margin["left"] <= threshold_x <= width - margin["right"]:
        parts.append(f'<line x1="{threshold_x:.2f}" y1="{margin["top"]}" x2="{threshold_x:.2f}" y2="{height - margin["bottom"]}" stroke="#7c3aed" stroke-width="2.5" stroke-dasharray="8 5"/>')
        parts.append(_svg_text(threshold_x + 6, margin["top"] + 16, "阈值τ", size=12))

    parts.append(f'<rect x="{margin["left"]}" y="50" width="12" height="12" fill="#2563eb"/>')
    parts.append(_svg_text(margin["left"] + 18, 61, "正常窗口", size=12))
    parts.append(f'<rect x="{margin["left"] + 110}" y="50" width="12" height="12" fill="#dc2626"/>')
    parts.append(_svg_text(margin["left"] + 128, 61, "异常窗口", size=12))
    parts.append(_svg_text(width / 2, height - 14, "重构误差区间", size=13, anchor="middle"))
    parts.append(_svg_text(18, height / 2, "窗口数量", size=13, anchor="middle", rotate=-90))
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _write_line_svg(
    path: Path,
    title: str,
    x_label: str,
    y_label: str,
    series: list[tuple[str, list[float], list[float], str]],
    *,
    x_range: tuple[float, float] | None = None,
    y_range: tuple[float, float] | None = None,
) -> None:
    width, height = 920, 460
    margin = {"left": 72, "right": 36, "top": 78, "bottom": 72}
    chart_w = width - margin["left"] - margin["right"]
    chart_h = height - margin["top"] - margin["bottom"]

    all_x = [float(value) for _, xs, _, _ in series for value in xs]
    all_y = [float(value) for _, _, ys, _ in series for value in ys]
    min_x, max_x = x_range or _range(all_x)
    min_y, max_y = y_range or _range(all_y)

    def sx(value: float) -> float:
        return margin["left"] + (float(value) - min_x) / max(1e-12, max_x - min_x) * chart_w

    def sy(value: float) -> float:
        return margin["top"] + chart_h - (float(value) - min_y) / max(1e-12, max_y - min_y) * chart_h

    parts = [_svg_header(width, height), _svg_text(width / 2, 32, title, size=22, weight="700", anchor="middle")]
    parts.append(_axis(margin, width, height))
    for i in range(6):
        y = margin["top"] + chart_h - chart_h * i / 5
        value = min_y + (max_y - min_y) * i / 5
        parts.append(f'<line x1="{margin["left"]}" y1="{y:.2f}" x2="{width - margin["right"]}" y2="{y:.2f}" stroke="#e5e7eb"/>')
        parts.append(_svg_text(margin["left"] - 10, y + 4, f"{value:.3g}", size=11, anchor="end"))
    for i in range(6):
        x = margin["left"] + chart_w * i / 5
        value = min_x + (max_x - min_x) * i / 5
        parts.append(_svg_text(x, height - 45, f"{value:.3g}", size=11, anchor="middle"))
    for name, xs, ys, color in series:
        points = " ".join(f"{sx(x):.2f},{sy(y):.2f}" for x, y in zip(xs, ys))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.5"/>')
    legend_x = margin["left"]
    for index, (name, _, _, color) in enumerate(series):
        x = legend_x + index * 180
        parts.append(f'<line x1="{x}" y1="52" x2="{x + 24}" y2="52" stroke="{color}" stroke-width="3"/>')
        parts.append(_svg_text(x + 32, 56, name, size=12))
    parts.append(_svg_text(width / 2, height - 14, x_label, size=13, anchor="middle"))
    parts.append(_svg_text(18, height / 2, y_label, size=13, anchor="middle", rotate=-90))
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _range(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 1.0
    min_value = float(min(values))
    max_value = float(max(values))
    if abs(max_value - min_value) < 1e-12:
        return min_value - 0.5, max_value + 0.5
    padding = (max_value - min_value) * 0.08
    return min_value - padding, max_value + padding


def _svg_header(width: int, height: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#ffffff"/>'
    )


def _axis(margin: dict[str, int], width: int, height: int) -> str:
    x1 = margin["left"]
    y1 = height - margin["bottom"]
    x2 = width - margin["right"]
    y2 = margin["top"]
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y1}" stroke="#111827" stroke-width="1.2"/>'
        f'<line x1="{x1}" y1="{y1}" x2="{x1}" y2="{y2}" stroke="#111827" stroke-width="1.2"/>'
    )


def _svg_text(
    x: float,
    y: float,
    text: str,
    *,
    size: int = 12,
    weight: str = "400",
    anchor: str = "start",
    rotate: int | None = None,
) -> str:
    transform = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ""
    escaped = _escape(text)
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-family="Arial, Microsoft YaHei, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" fill="#111827"{transform}>{escaped}</text>'
    )


def _escape(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    main()
