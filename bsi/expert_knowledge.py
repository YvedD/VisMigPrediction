"""
bsi/expert_knowledge.py
Slaat meteorologische vingerafdrukken en uur-profielen op per vogelgilde.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ExpertKnowledgeBase:
    discovered_krenten: List[str] = field(default_factory=list)
    pinned_species: List[str] = field(default_factory=list)
    excluded_species: List[str] = field(default_factory=list)
    hourly_profiles: Dict[str, List[float]] = field(default_factory=dict)
    peak_days_by_guild: Dict[str, List[int]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "discoveredKrenten": self.discovered_krenten,
            "pinnedSpecies": self.pinned_species,
            "excludedSpecies": self.excluded_species,
            "hourlyProfiles": self.hourly_profiles,
            "peakDaysByGuild": self.peak_days_by_guild,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExpertKnowledgeBase":
        return cls(
            discovered_krenten=d.get("discoveredKrenten", []),
            pinned_species=d.get("pinnedSpecies", []),
            excluded_species=d.get("excludedSpecies", []),
            hourly_profiles=d.get("hourlyProfiles", {}),
            peak_days_by_guild=d.get("peakDaysByGuild", {}),
        )