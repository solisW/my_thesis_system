from __future__ import annotations

import argparse
import json

import joblib
import pandas as pd
import torch

from .config import FEATURE_COLUMNS, META_FILE, MODEL_FILE, PREDICTION_FILE, SCALER_FILE, ensure_directories
from .model import LSTMAutoEncoder
from .preprocess import build_windows, clean_dataset, load_dataset, transform_features


def run_prediction(input_path: str, output_path: str | None = None) -> pd.DataFrame:
    ensure_directories()
    frame = clean_dataset(load_dataset(input_path))
    scaler = joblib.load(SCALER_FILE)
    meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    window_size = meta["window_size"]

    transformed = transform_features(frame, scaler)
    windows, metadata = build_windows(transformed, window_size)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = LSTMAutoEncoder(
        input_size=len(FEATURE_COLUMNS),
        hidden_size=meta["hidden_size"],
        num_layers=meta["num_layers"],
    ).to(device)
    model.load_state_dict(torch.load(MODEL_FILE, map_location=device))
    model.eval()

    with torch.no_grad():
        tensor = torch.tensor(windows, dtype=torch.float32, device=device)
        reconstructed = model(tensor)
        scores = torch.mean((reconstructed - tensor) ** 2, dim=(1, 2)).cpu().numpy()

    result = pd.DataFrame(metadata)
    result["anomaly_score"] = scores
    result["threshold"] = meta["threshold"]
    result["predicted_label"] = (result["anomaly_score"] > result["threshold"]).astype(int)

    destination = output_path or str(PREDICTION_FILE)
    result.to_csv(destination, index=False, encoding="utf-8-sig")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="智能燃气表异常检测")
    parser.add_argument("--input", required=True, help="输入 CSV 文件路径")
    parser.add_argument("--output", required=False, help="输出 CSV 文件路径")
    args = parser.parse_args()

    result = run_prediction(args.input, args.output)
    print(result.head(10).to_string(index=False))
    print(f"检测结果已保存，共 {len(result)} 条窗口记录。")


if __name__ == "__main__":
    main()
