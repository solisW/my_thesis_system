from __future__ import annotations

import torch
from torch import nn


class LSTMAutoEncoder(nn.Module):
    def __init__(self, input_size: int, hidden_size: int, num_layers: int) -> None:
        super().__init__()
        self.encoder = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
        )
        self.decoder = nn.LSTM(
            input_size=hidden_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
        )
        self.output_layer = nn.Linear(hidden_size, input_size)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        _, (hidden, _) = self.encoder(inputs)
        repeated_context = hidden[-1].unsqueeze(1).repeat(1, inputs.size(1), 1)
        decoded, _ = self.decoder(repeated_context)
        return self.output_layer(decoded)
