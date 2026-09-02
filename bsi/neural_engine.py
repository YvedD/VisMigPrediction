"""
bsi/neural_engine.py
Neuraal Netwerk (MLP) voor BSI vogelprognoses.
"""

import json
import numpy as np
from typing import Dict, Any


class LiteNeuralEngine:
    def __init__(self, input_size: int = 21, hidden_size: int = 32, output_size: int = 1000):
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.output_size = output_size

        self.w_input_hidden = np.random.uniform(-0.05, 0.05, (input_size, hidden_size)).astype(np.float32)
        self.b_hidden = np.zeros(hidden_size, dtype=np.float32)

        self.w_hidden_output = np.random.uniform(-0.05, 0.05, (hidden_size, output_size)).astype(np.float32)
        self.b_output = np.zeros(output_size, dtype=np.float32)

    @staticmethod
    def relu(x: np.ndarray) -> np.ndarray:
        return np.maximum(0.0, x)

    @staticmethod
    def softmax(logits: np.ndarray) -> np.ndarray:
        max_logit = np.max(logits)
        exp_vals = np.exp(logits - max_logit)
        sum_exp = np.sum(exp_vals)
        return exp_vals / (sum_exp if sum_exp > 0 else 1e-8)

    def predict(self, inputs: np.ndarray) -> np.ndarray:
        inputs = np.asarray(inputs, dtype=np.float32)
        hidden_layer = self.relu(np.dot(inputs, self.w_input_hidden) + self.b_hidden)
        output_logits = np.dot(hidden_layer, self.w_hidden_output) + self.b_output
        return self.softmax(output_logits)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inputSize": self.input_size,
            "hiddenSize": self.hidden_size,
            "outputSize": self.output_size,
            "wInputHidden": self.w_input_hidden.tolist(),
            "bHidden": self.b_hidden.tolist(),
            "wHiddenOutput": self.w_hidden_output.tolist(),
            "bOutput": self.b_output.tolist(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LiteNeuralEngine":
        engine = cls(
            input_size=d.get("inputSize", 21),
            hidden_size=d.get("hiddenSize", 32),
            output_size=d.get("outputSize", 1000)
        )
        engine.w_input_hidden = np.array(d["wInputHidden"], dtype=np.float32)
        engine.b_hidden = np.array(d["bHidden"], dtype=np.float32)
        engine.w_hidden_output = np.array(d["wHiddenOutput"], dtype=np.float32)
        engine.b_output = np.array(d["bOutput"], dtype=np.float32)
        return engine