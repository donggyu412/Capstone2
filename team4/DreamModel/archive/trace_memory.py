"""Shared, fading object traces: H(t + 1) = retention * H(t) + deposit(t)."""

from __future__ import annotations

import numpy as np


def sample_field(field: np.ndarray, positions: np.ndarray) -> np.ndarray:
    """Bilinearly sample scalar/vector grids using normalized x/y positions."""
    positions = np.asarray(positions, dtype=np.float64).reshape(-1, 2)
    if not np.isfinite(positions).all():
        raise ValueError("positions must contain finite coordinates")
    height, width = field.shape[:2]
    coordinates = np.clip(positions, 0, 1) * (width - 1, height - 1)
    lower = np.floor(coordinates).astype(int)
    upper = np.minimum(lower + 1, (width - 1, height - 1))
    fraction = coordinates - lower
    if field.ndim == 3:
        fraction = fraction[:, :, None]
    x0, y0 = lower.T
    x1, y1 = upper.T
    fx, fy = fraction[:, 0], fraction[:, 1]
    return (
        field[y0, x0] * (1 - fx) * (1 - fy)
        + field[y0, x1] * fx * (1 - fy)
        + field[y1, x0] * (1 - fx) * fy
        + field[y1, x1] * fx * fy
    )


class TraceMemory:
    """One low-resolution memory shared by all agents and successive scenes.

    The grid is a record of deposits, not a cellular automaton: there is no
    neighborhood growth rule. Gradients are measured per memory-grid cell.
    """

    def __init__(
        self,
        width: int = 128,
        height: int = 72,
        decay: float = 0.985,
        deposit_strength: float = 0.045,
        radius: float = 2.0,
    ) -> None:
        if width < 2 or height < 2:
            raise ValueError("trace dimensions must both be at least 2")
        if not 0 <= decay < 1:
            raise ValueError("trace decay must be in [0, 1)")
        if not np.isfinite(deposit_strength) or deposit_strength < 0:
            raise ValueError("deposit strength must be finite and nonnegative")
        if not np.isfinite(radius) or radius <= 0:
            raise ValueError("trace radius must be finite and positive")
        self.field = np.zeros((height, width), dtype=np.float32)
        self.decay = float(decay)
        self.deposit_strength = float(deposit_strength)
        self.radius = float(radius)

    def gradient(self, positions: np.ndarray, sensing_radius: float = 0.0) -> np.ndarray:
        """Read old traces before this frame's agents deposit new traces."""
        vertical, horizontal = np.gradient(self.field)
        local = sample_field(np.stack((horizontal, vertical), axis=-1), positions)
        if sensing_radius == 0:
            return local
        if not 0 < sensing_radius <= .2:
            raise ValueError("Trace sensing radius must be in (0, 0.2]")
        # Finite-footprint gradient sensing lets a sprite respond to a path
        # near its edges. It reads H only: no diffusion, CA or visual widening.
        angles = np.arange(12) * (2 * np.pi / 12)
        directions = np.column_stack((np.cos(angles), np.sin(angles)))
        field_size = np.array((self.field.shape[1] - 1, self.field.shape[0] - 1))
        footprint = np.zeros_like(local)
        for radius in (sensing_radius * .5, sensing_radius, sensing_radius * 1.5):
            points = np.asarray(positions)[:, None, :] + radius * directions[None, :, :]
            values = sample_field(self.field, points.reshape(-1, 2)).reshape(-1, 12)
            footprint += 2 * (values @ directions) / (12 * radius * field_size)
        return .30 * local + .70 * footprint / 3

    def update(self, positions: np.ndarray, energies: np.ndarray) -> None:
        positions = np.asarray(positions, dtype=np.float64).reshape(-1, 2)
        energies = np.asarray(energies, dtype=np.float64).reshape(-1)
        if len(positions) != len(energies):
            raise ValueError("each position needs one deposition energy")
        if not np.isfinite(positions).all() or not np.isfinite(energies).all():
            raise ValueError("trace positions and energies must be finite")
        if (energies < 0).any():
            raise ValueError("deposition energy cannot be negative")

        # Project formula 1. D is a sum of small Gaussian footprints; no
        # clipping or per-frame normalization discards accumulated history.
        self.field *= self.decay
        height, width = self.field.shape
        extent = int(np.ceil(3 * self.radius))
        for position, energy in zip(positions, energies):
            x, y = np.clip(position, 0, 1) * (width - 1, height - 1)
            left, right = max(0, int(x) - extent), min(width, int(x) + extent + 2)
            top, bottom = max(0, int(y) - extent), min(height, int(y) + extent + 2)
            yy, xx = np.mgrid[top:bottom, left:right]
            deposit = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * self.radius**2))
            self.field[top:bottom, left:right] += deposit * self.deposit_strength * energy

    def retain(self, fraction: float = 0.35) -> None:
        """Carry a deliberate portion of the same memory into the next scene."""
        if not np.isfinite(fraction) or not 0 <= fraction <= 1:
            raise ValueError("memory carryover must be in [0, 1]")
        self.field *= fraction
