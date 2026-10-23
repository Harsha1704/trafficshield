"""
CPU-Friendly Autoencoder Anomaly Detector
=========================================
Version: 1.0 (Milestone 8)

Unsupervised neural anomaly detector using a symmetric encoder-decoder architecture.
Reconstruction error (MSE) serves as the continuous anomaly score.

Key Characteristics:
1. CONSISTENT SCORE CONVENTION: Anomaly score is sample-level reconstruction MSE:
       score(x) = (1 / D) * sum_{j=1}^D (x_j - x_hat_j)^2
   Higher scores strictly and consistently indicate greater anomalousness (poorer reconstruction).
2. CPU-FIRST EXECUTION: Designed for bounded, CPU-friendly training and inference without
   GPU or CUDA dependencies.
3. ADAPTIVE BACKEND:
   - When PyTorch is available, executes via torch.nn and Adam.
   - When PyTorch is unavailable, executes via an exact, lightweight, vectorized pure-NumPy
     feedforward autoencoder with Adam optimization and early stopping.
   - If backend="torch" is explicitly requested when torch is missing, raises an informative
     ImportError directing the user to install torch or use backend="numpy".
4. ZERO DATA LEAKAGE:
   - Rejects prohibited reverse-direction features and evaluation labels via _validate_data().
   - Validation split for early stopping is drawn strictly from the training partition.
   - Decision thresholds are calibrated on the independent calibration partition, never test labels.
5. IMMUTABLE PARAMETERS: Parameters and thresholds remain strictly frozen during inference.
6. SECURE REPRODUCIBILITY: Supports deterministic random seeding and joblib artifact persistence
   with SHA-256 provenance tracking.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np
import pandas as pd

from detection.base import BaseDetector

logger = logging.getLogger(__name__)

# Check PyTorch availability safely
try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    TORCH_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    DataLoader = None  # type: ignore[assignment]
    TensorDataset = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# PyTorch Neural Module (used when torch is installed)
# ─────────────────────────────────────────────────────────────────────────────

if TORCH_AVAILABLE:

    class _PyTorchAEModule(nn.Module):
        """Symmetric Fully Connected Autoencoder in PyTorch."""

        def __init__(self, input_dim: int, hidden_dims: list[int] | tuple[int, ...]) -> None:
            super().__init__()
            # Encoder: input_dim -> hidden_0 -> ... -> hidden_k
            encoder_layers: list[nn.Module] = []
            curr_dim = input_dim
            for h_dim in hidden_dims:
                encoder_layers.append(nn.Linear(curr_dim, h_dim))
                encoder_layers.append(nn.ReLU())
                curr_dim = h_dim
            self.encoder = nn.Sequential(*encoder_layers)

            # Decoder: hidden_k -> ... -> hidden_0 -> input_dim
            decoder_layers: list[nn.Module] = []
            rev_dims = list(reversed(list(hidden_dims)))[1:] + [input_dim]
            for i, h_dim in enumerate(rev_dims):
                decoder_layers.append(nn.Linear(curr_dim, h_dim))
                if i < len(rev_dims) - 1:
                    decoder_layers.append(nn.ReLU())
                curr_dim = h_dim
            self.decoder = nn.Sequential(*decoder_layers)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            latent = self.encoder(x)
            recon = self.decoder(latent)
            return recon

else:
    _PyTorchAEModule = None  # type: ignore[assignment, misc]


# ─────────────────────────────────────────────────────────────────────────────
# Pure-NumPy Reference Autoencoder (used when torch is not installed)
# ─────────────────────────────────────────────────────────────────────────────

class _NumpyAEModel:
    """
    Lightweight, vectorized CPU feedforward autoencoder with Adam optimization.
    Provides identical API and behavior without requiring PyTorch binary installation.
    """

    def __init__(
        self,
        input_dim: int,
        hidden_dims: list[int] | tuple[int, ...],
        learning_rate: float = 1e-3,
        random_state: int | None = 42,
    ) -> None:
        self.input_dim = input_dim
        self.hidden_dims = list(hidden_dims)
        self.learning_rate = learning_rate
        self.random_state = random_state

        rng = np.random.default_rng(random_state)

        # Build layer dimensions: [input_dim, h1, h2, ..., h2, h1, input_dim]
        enc_dims = [input_dim] + self.hidden_dims
        dec_dims = list(reversed(self.hidden_dims)) + [input_dim]
        all_dims = enc_dims + dec_dims[1:]

        self.weights: list[np.ndarray] = []
        self.biases: list[np.ndarray] = []

        # He / Xavier initialization
        for i in range(len(all_dims) - 1):
            d_in, d_out = all_dims[i], all_dims[i + 1]
            scale = np.sqrt(2.0 / d_in)
            w = rng.normal(0.0, scale, size=(d_in, d_out)).astype(np.float64)
            b = np.zeros(d_out, dtype=np.float64)
            self.weights.append(w)
            self.biases.append(b)

        # Adam optimizer state
        self.m_w = [np.zeros_like(w) for w in self.weights]
        self.v_w = [np.zeros_like(w) for w in self.weights]
        self.m_b = [np.zeros_like(b) for b in self.biases]
        self.v_b = [np.zeros_like(b) for b in self.biases]
        self.t = 0

    def _forward(self, X: np.ndarray) -> tuple[list[np.ndarray], list[np.ndarray]]:
        """Compute forward activations."""
        activations = [X]
        linear_outputs = []
        num_layers = len(self.weights)

        a = X
        for i in range(num_layers):
            z = np.dot(a, self.weights[i]) + self.biases[i]
            linear_outputs.append(z)
            if i < num_layers - 1:
                # ReLU activation
                a = np.maximum(0.0, z)
            else:
                # Linear output for reconstruction
                a = z
            activations.append(a)

        return activations, linear_outputs

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Reconstruct input array."""
        activations, _ = self._forward(X)
        return activations[-1]

    def train_step(self, X_batch: np.ndarray) -> float:
        """Run single mini-batch forward + backpropagation + Adam step."""
        batch_size = X_batch.shape[0]
        activations, linear_outputs = self._forward(X_batch)
        x_pred = activations[-1]

        # MSE loss: (1 / (N * D)) * sum((x_pred - X)^2)
        diff = x_pred - X_batch
        loss = float(np.mean(diff ** 2))

        # Gradient of MSE wrt x_pred: (2 / (N * D)) * diff
        grad_out = (2.0 / (batch_size * self.input_dim)) * diff

        # Backpropagation
        delta = grad_out
        num_layers = len(self.weights)

        grad_w: list[np.ndarray] = []
        grad_b: list[np.ndarray] = []

        for i in reversed(range(num_layers)):
            dw = np.dot(activations[i].T, delta)
            db = np.sum(delta, axis=0)
            grad_w.insert(0, dw)
            grad_b.insert(0, db)

            if i > 0:
                # Propagate delta through ReLU
                delta = np.dot(delta, self.weights[i].T)
                relu_mask = (linear_outputs[i - 1] > 0).astype(np.float64)
                delta = delta * relu_mask

        # Adam optimization update
        self.t += 1
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        for i in range(num_layers):
            # Weights
            self.m_w[i] = beta1 * self.m_w[i] + (1 - beta1) * grad_w[i]
            self.v_w[i] = beta2 * self.v_w[i] + (1 - beta2) * (grad_w[i] ** 2)
            m_hat_w = self.m_w[i] / (1.0 - beta1 ** self.t)
            v_hat_w = self.v_w[i] / (1.0 - beta2 ** self.t)
            self.weights[i] -= self.learning_rate * m_hat_w / (np.sqrt(v_hat_w) + eps)

            # Biases
            self.m_b[i] = beta1 * self.m_b[i] + (1 - beta1) * grad_b[i]
            self.v_b[i] = beta2 * self.v_b[i] + (1 - beta2) * (grad_b[i] ** 2)
            m_hat_b = self.m_b[i] / (1.0 - beta1 ** self.t)
            v_hat_b = self.v_b[i] / (1.0 - beta2 ** self.t)
            self.biases[i] -= self.learning_rate * m_hat_b / (np.sqrt(v_hat_b) + eps)

        return loss


# ─────────────────────────────────────────────────────────────────────────────
# TrafficShield Autoencoder Anomaly Detector
# ─────────────────────────────────────────────────────────────────────────────

class AutoencoderDetector(BaseDetector):
    """
    TrafficShield Autoencoder Anomaly Detector.

    Fits an unsupervised neural autoencoder on normal training traffic features.
    Anomaly score is the mean squared reconstruction error per flow.
    """

    def __init__(
        self,
        hidden_dims: list[int] | tuple[int, ...] = (32, 16),
        learning_rate: float = 1e-3,
        epochs: int = 20,
        batch_size: int = 128,
        early_stopping: bool = True,
        patience: int = 3,
        val_split: float = 0.1,
        random_state: int | None = 42,
        threshold: float | None = None,
        backend: Literal["auto", "torch", "numpy"] = "auto",
    ) -> None:
        """
        Parameters
        ----------
        hidden_dims : sequence of int
            Encoder hidden dimensions from outer to bottleneck (e.g. (32, 16)).
        learning_rate : float
            Optimizer learning rate (default: 1e-3).
        epochs : int
            Maximum training epochs (default: 20).
        batch_size : int
            Mini-batch size for gradient descent (default: 128).
        early_stopping : bool
            Whether to halt training when validation reconstruction loss ceases improving.
        patience : int
            Number of epochs with no validation loss improvement before early stop.
        val_split : float
            Fraction of training partition reserved for validation early-stopping (default: 0.1).
        random_state : int or None
            Deterministic seed for weight initialization and batch shuffling.
        threshold : float or None
            Established anomaly threshold.
        backend : 'auto', 'torch', or 'numpy'
            Execution backend. 'auto' selects torch if available, else numpy reference.
        """
        super().__init__(threshold=threshold)
        self.hidden_dims = list(hidden_dims)
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.batch_size = batch_size
        self.early_stopping = early_stopping
        self.patience = patience
        self.val_split = val_split
        self.random_state = random_state
        self.backend = backend

        # Internal state
        self.backend_used_: str | None = None
        self.model_: Any = None
        self.train_loss_history_: list[float] = []
        self.val_loss_history_: list[float] = []

    @property
    def torch_available(self) -> bool:
        """Return True if PyTorch is available in current environment."""
        return TORCH_AVAILABLE

    def _resolve_backend(self) -> str:
        """Determine whether to use PyTorch or NumPy backend."""
        if self.backend == "torch":
            if not TORCH_AVAILABLE:
                raise ImportError(
                    "PyTorch (torch) is not installed in the current environment. "
                    "AutoencoderDetector requires PyTorch when backend='torch'. "
                    "To proceed, install torch or configure backend='numpy' for "
                    "the lightweight CPU reference implementation."
                )
            return "torch"
        elif self.backend == "numpy":
            return "numpy"
        elif self.backend == "auto":
            return "torch" if TORCH_AVAILABLE else "numpy"
        else:
            raise ValueError(f"Unknown backend '{self.backend}'. Must be 'auto', 'torch', or 'numpy'.")

    def fit(
        self,
        X: pd.DataFrame | np.ndarray,
        y: Any = None,
    ) -> AutoencoderDetector:
        """
        Fit autoencoder on training features only.

        Parameters
        ----------
        X : pd.DataFrame or np.ndarray of shape (n_samples, n_features)
            Eligible training feature matrix.
        y : None
            Ignored. primary training is strictly unsupervised.
        """
        arr = self._validate_data(X, is_fit=True)
        n_samples, n_features = arr.shape

        backend_to_use = self._resolve_backend()
        self.backend_used_ = backend_to_use

        # Chronological or random train/val split within training data only
        rng = np.random.default_rng(self.random_state)
        if self.val_split > 0.0 and n_samples > 10:
            val_size = max(1, int(n_samples * self.val_split))
            train_size = n_samples - val_size
            indices = np.arange(n_samples)
            if self.random_state is not None:
                rng.shuffle(indices)
            train_idx, val_idx = indices[:train_size], indices[train_size:]
            x_train, x_val = arr[train_idx], arr[val_idx]
        else:
            x_train, x_val = arr, arr[:0]

        if backend_to_use == "torch":
            self._fit_torch(x_train, x_val, n_features)
        else:
            self._fit_numpy(x_train, x_val, n_features)

        self.is_fitted_ = True
        logger.debug(
            "Fitted AutoencoderDetector (%s backend) on %d samples, %d features across %d epochs.",
            self.backend_used_, n_samples, n_features, len(self.train_loss_history_),
        )
        return self

    def _fit_numpy(self, X_train: np.ndarray, X_val: np.ndarray, n_features: int) -> None:
        """Train pure-NumPy reference autoencoder."""
        self.model_ = _NumpyAEModel(
            input_dim=n_features,
            hidden_dims=self.hidden_dims,
            learning_rate=self.learning_rate,
            random_state=self.random_state,
        )

        n_train = X_train.shape[0]
        rng = np.random.default_rng(self.random_state)
        best_val_loss = float("inf")
        patience_counter = 0
        best_weights = [w.copy() for w in self.model_.weights]
        best_biases = [b.copy() for b in self.model_.biases]

        self.train_loss_history_ = []
        self.val_loss_history_ = []

        for _ in range(self.epochs):
            # Shuffle mini-batches
            shuffled_idx = np.arange(n_train)
            rng.shuffle(shuffled_idx)

            epoch_losses = []
            for start_idx in range(0, n_train, self.batch_size):
                batch_idx = shuffled_idx[start_idx : start_idx + self.batch_size]
                batch_loss = self.model_.train_step(X_train[batch_idx])
                epoch_losses.append(batch_loss)

            mean_train_loss = float(np.mean(epoch_losses)) if epoch_losses else 0.0
            self.train_loss_history_.append(mean_train_loss)

            # Validation loss evaluation
            if X_val.shape[0] > 0:
                val_recon = self.model_.predict(X_val)
                val_loss = float(np.mean((val_recon - X_val) ** 2))
                self.val_loss_history_.append(val_loss)

                if self.early_stopping:
                    if val_loss < best_val_loss - 1e-5:
                        best_val_loss = val_loss
                        patience_counter = 0
                        best_weights = [w.copy() for w in self.model_.weights]
                        best_biases = [b.copy() for b in self.model_.biases]
                    else:
                        patience_counter += 1
                        if patience_counter >= self.patience:
                            # Restore best weights and exit early
                            self.model_.weights = best_weights
                            self.model_.biases = best_biases
                            break

    def _fit_torch(self, X_train: np.ndarray, X_val: np.ndarray, n_features: int) -> None:
        """Train PyTorch CPU autoencoder."""
        if torch is None or nn is None or DataLoader is None or TensorDataset is None:
            raise RuntimeError("PyTorch is not imported.")

        if self.random_state is not None:
            torch.manual_seed(self.random_state)

        device = torch.device("cpu")
        model = _PyTorchAEModule(input_dim=n_features, hidden_dims=self.hidden_dims).to(device)
        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=self.learning_rate)

        tensor_train = torch.tensor(X_train, dtype=torch.float32)
        dataset = TensorDataset(tensor_train, tensor_train)
        loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

        has_val = X_val.shape[0] > 0
        if has_val:
            tensor_val = torch.tensor(X_val, dtype=torch.float32).to(device)

        best_val_loss = float("inf")
        patience_counter = 0
        best_state = None

        self.train_loss_history_ = []
        self.val_loss_history_ = []

        model.train()
        for _ in range(self.epochs):
            batch_losses = []
            for batch_x, _ in loader:
                batch_x = batch_x.to(device)
                optimizer.zero_grad()
                recon = model(batch_x)
                loss = criterion(recon, batch_x)
                loss.backward()
                optimizer.step()
                batch_losses.append(loss.item())

            mean_train_loss = float(np.mean(batch_losses)) if batch_losses else 0.0
            self.train_loss_history_.append(mean_train_loss)

            if has_val:
                model.eval()
                with torch.no_grad():
                    val_recon = model(tensor_val)
                    val_loss = criterion(val_recon, tensor_val).item()
                    self.val_loss_history_.append(val_loss)

                if self.early_stopping:
                    if val_loss < best_val_loss - 1e-5:
                        best_val_loss = val_loss
                        patience_counter = 0
                        best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                    else:
                        patience_counter += 1
                        if patience_counter >= self.patience:
                            if best_state is not None:
                                model.load_state_dict(best_state)
                            break
                model.train()

        model.eval()
        self.model_ = model

    def score_samples_raw(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Compute reconstruction Mean Squared Error per sample.
        Identical to score_samples() since reconstruction error is directly
        the anomaly score.
        """
        return self.score_samples(X)

    def score_samples(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        """
        Compute reconstruction MSE per flow.

        Returns
        -------
        np.ndarray of shape (n_samples,) where HIGHER values strictly indicate
        GREATER anomalousness.
        """
        if not self.is_fitted_ or self.model_ is None:
            raise RuntimeError(f"{self.__class__.__name__} must be fitted before scoring samples.")

        arr = self._validate_data(X, is_fit=False)

        if self.backend_used_ == "torch":
            if torch is None:
                raise RuntimeError("PyTorch model fitted, but torch is unavailable at scoring time.")
            self.model_.eval()
            device = torch.device("cpu")
            with torch.no_grad():
                tensor_x = torch.tensor(arr, dtype=torch.float32).to(device)
                recon = self.model_(tensor_x)
                # MSE per sample across features: mean across axis 1
                diff_sq = (recon - tensor_x) ** 2
                mse_tensor = torch.mean(diff_sq, dim=1)
                scores = mse_tensor.cpu().numpy().astype(np.float64)
        else:
            recon = self.model_.predict(arr)
            diff_sq = (recon - arr) ** 2
            scores = np.mean(diff_sq, axis=1).astype(np.float64)

        if not np.all(np.isfinite(scores)):
            raise ValueError("Autoencoder computed non-finite anomaly scores.")

        return np.asarray(scores, dtype=np.float64)

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        """Return hyperparameter configuration dictionary."""
        return {
            "hidden_dims": self.hidden_dims,
            "learning_rate": self.learning_rate,
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "early_stopping": self.early_stopping,
            "patience": self.patience,
            "val_split": self.val_split,
            "random_state": self.random_state,
            "threshold": self.threshold,
            "backend": self.backend,
            "backend_used": self.backend_used_,
        }
