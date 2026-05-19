from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "data" / "experiment_results"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "picturesfinal" / "model_curves"
MPL_CACHE_DIR = PROJECT_ROOT / ".matplotlib_cache"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate thesis-ready LSTM AutoEncoder curve figures.")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR), help="Directory containing experiment CSV files.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for generated PNG figures.")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(MPL_CACHE_DIR))

    import matplotlib.pyplot as plt

    _configure_matplotlib(plt)

    normal_case = _read_csv(source_dir / "normal_reconstruction_case.csv")
    anomaly_case = _read_csv(source_dir / "reconstruction_case.csv")
    loss_curve = _read_csv(source_dir / "loss_curve.csv")

    _plot_reconstruction_case(
        plt=plt,
        frame=normal_case,
        output_path=output_dir / "正常样本原始与重构曲线.png",
    )
    _plot_reconstruction_case(
        plt=plt,
        frame=anomaly_case,
        output_path=output_dir / "异常样本原始与重构曲线.png",
    )
    _plot_loss_curve(
        plt=plt,
        frame=loss_curve,
        output_path=output_dir / "训练损失变化曲线.png",
    )

    print(f"Generated model curve figures: {output_dir}")


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing experiment CSV: {path}")
    return pd.read_csv(path)


def _configure_matplotlib(plt) -> None:
    plt.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "figure.dpi": 120,
            "savefig.dpi": 300,
            "axes.linewidth": 1.2,
            "axes.labelsize": 13,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.fontsize": 12,
        }
    )


def _plot_reconstruction_case(plt, frame: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.plot(
        frame["step"],
        frame["original_flow"],
        color="#0057FF",
        linewidth=2.4,
        marker="o",
        markersize=4.8,
        label="原始流量",
    )
    ax.plot(
        frame["step"],
        frame["reconstructed_flow"],
        color="#FF3B00",
        linewidth=2.4,
        linestyle="--",
        marker="s",
        markersize=4.5,
        label="重构流量",
    )
    ax.set_xlabel("时间步")
    ax.set_ylabel("瞬时流量")
    ax.grid(True, linestyle="--", linewidth=0.8, alpha=0.32)
    ax.legend(loc="best", frameon=True, framealpha=0.95, edgecolor="#D0D0D0")
    ax.margins(x=0.025)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def _plot_loss_curve(plt, frame: pd.DataFrame, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.plot(
        frame["epoch"],
        frame["train_loss"],
        color="#0B8F3A",
        linewidth=2.4,
        marker="o",
        markersize=4.8,
        label="训练损失",
    )
    ax.plot(
        frame["epoch"],
        frame["valid_loss"],
        color="#D21F3C",
        linewidth=2.4,
        linestyle="--",
        marker="s",
        markersize=4.5,
        label="验证损失",
    )
    ax.set_xlabel("训练轮次")
    ax.set_ylabel("MSE 损失")
    ax.grid(True, linestyle="--", linewidth=0.8, alpha=0.32)
    ax.legend(loc="best", frameon=True, framealpha=0.95, edgecolor="#D0D0D0")
    ax.margins(x=0.025)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
