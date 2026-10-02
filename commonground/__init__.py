"""CommonGround domain logic."""

from .candidates import generate_candidate_areas
from .fairness import score_fairest_option
from .fastest import score_fastest_option
from .locations import resolve_group_locations
from .transit import get_transit_matrix

__all__ = [
    "generate_candidate_areas",
    "get_transit_matrix",
    "resolve_group_locations",
    "score_fairest_option",
    "score_fastest_option",
]
