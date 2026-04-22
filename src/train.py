from __future__ import annotations

import json

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
    NUM_LAYERS,
    SCALER_FILE,
    TRAIN_EPOCHS,
    TRAIN_SPLIT,
    WINDOW_SIZE,
    ensure_directories,
)
from .model import LSTMAutoEncoder
from .preprocess import build_windows, clean_dataset, fit_scaler, load_dataset, transform_features


def compute_reconstruction_errors(model: LSTMAutoEncoder, data: np.ndarray, device: torch.device) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        tensor = torch.tensor(data, dtype=torch.float32, device=device)
        reconstructed = model(tensor)
        errors = torch.mean((reconstructed - tensor) ** 2, dim=(1, 2))
    return errors.detach().cpu().numpy()


def train_model(frame=None) -> float:
    ensure_directories()
    if frame is None:
        frame = load_dataset()
    frame = clean_dataset(frame)
    scaler = fit_scaler(frame)
    transformed = transform_features(frame, scaler)
    windows, metadata = build_windows(transformed, WINDOW_SIZE)

    normal_indices = [idx for idx, item in enumerate(metadata) if item["window_has_anomaly"] == 0]
    normal_windows = windows[normal_indices]

    split_index = max(1, int(len(normal_windows) * TRAIN_SPLIT))
    train_windows = normal_windows[:split_index]
    valid_windows = normal_windows[split_index:] if split_index < len(normal_windows) else normal_windows[:1]

    train_dataset = TensorDataset(torch.tensor(train_windows, dtype=torch.float32))
    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = LSTMAutoEncoder(
        input_size=len(FEATURE_COLUMNS),
        hidden_size=HIDDEN_SIZE,
        num_layers=NUM_LAYERS,
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.MSELoss()

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

        avg_loss = epoch_loss / max(1, len(train_loader))
        print(f"Epoch {epoch + 1}/{TRAIN_EPOCHS} - loss: {avg_loss:.6f}")

    valid_errors = compute_reconstruction_errors(model, valid_windows, device)
    threshold = float(np.mean(valid_errors) + 3 * np.std(valid_errors))

    torch.save(model.state_dict(), MODEL_FILE)
    joblib.dump(scaler, SCALER_FILE)
    META_FILE.write_text(
        json.dumps(
            {
                "feature_columns": FEATURE_COLUMNS,
                "window_size": WINDOW_SIZE,
                "hidden_size": HIDDEN_SIZE,
                "num_layers": NUM_LAYERS,
                "threshold": threshold,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"模型已保存: {MODEL_FILE}")
    print(f"阈值: {threshold:.6f}")
    return threshold


def main() -> None:
    train_model()


if __name__ == "__main__":
    main()
