"""Token budget management for LLM usage."""

from dataclasses import dataclass, field
from typing import Dict, List
from datetime import datetime


@dataclass
class TokenBudget:
    """Token budget manager.

    Tracks token usage and provides compression recommendations.
    """
    total_limit: int = 100000
    warning_threshold: float = 0.8
    enable_compression: bool = True

    def __post_init__(self):
        self._used: int = 0
        self._history: List[Dict] = []

    @property
    def remaining(self) -> int:
        """Remaining tokens."""
        return self.total_limit - self._used

    @property
    def usage_ratio(self) -> float:
        """Current usage ratio (0-1)."""
        return self._used / self.total_limit if self.total_limit > 0 else 0

    def consume(self, amount: int, source: str = "") -> bool:
        """Consume tokens from budget.

        Args:
            amount: Number of tokens to consume
            source: Source description for tracking

        Returns:
            True if within budget, False if exceeded
        """
        if amount < 0:
            raise ValueError("Token amount must be non-negative")

        new_total = self._used + amount
        self._history.append({
            "timestamp": datetime.now().isoformat(),
            "amount": amount,
            "source": source,
            "total_after": new_total,
            "remaining": self.total_limit - new_total
        })

        if new_total > self.total_limit:
            return False  # Exceeded budget

        self._used = new_total
        return True

    def should_warn(self) -> bool:
        """Check if usage exceeds warning threshold."""
        return self.usage_ratio >= self.warning_threshold

    def get_compression_ratio(self) -> float:
        """Get recommended compression ratio based on remaining tokens.

        Returns:
            Compression ratio (0-1), where 0 means no compression needed
            and 1 means maximum compression.
        """
        if not self.enable_compression:
            return 0.0

        if self.remaining > 20000:
            return 0.0
        elif self.remaining > 10000:
            return 0.3
        elif self.remaining > 5000:
            return 0.5
        else:
            return 0.7

    def reset(self) -> None:
        """Reset budget to initial state."""
        self._used = 0
        self._history = []

    def get_history(self) -> List[Dict]:
        """Get consumption history."""
        return self._history.copy()

    def get_summary(self) -> Dict:
        """Get budget summary."""
        return {
            "total_limit": self.total_limit,
            "used": self._used,
            "remaining": self.remaining,
            "usage_ratio": self.usage_ratio,
            "should_warn": self.should_warn(),
            "compression_ratio": self.get_compression_ratio()
        }
