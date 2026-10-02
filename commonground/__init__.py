"""CommonGround domain logic."""

from .fairness import score_fairest_option
from .fastest import score_fastest_option

__all__ = ["score_fairest_option", "score_fastest_option"]
