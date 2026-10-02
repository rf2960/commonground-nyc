"""CommonGround domain logic."""

from .fairness import score_fairest_option
from .fastest import score_fastest_option
from .locations import resolve_group_locations

__all__ = [
    "resolve_group_locations",
    "score_fairest_option",
    "score_fastest_option",
]
