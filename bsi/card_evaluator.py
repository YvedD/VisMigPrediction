"""
bsi/card_evaluator.py
Berekent de CardView metrieken: Norm Score, Heuristiek vs Prototype vergelijking, en Historische Pieken.
"""

import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass

from .inference_engine import VogelSuggestie
from .species_resolver import SpeciesResolver


@dataclass
class ComparativeCardData:
    soortid: str
    soortnaam: str
    latin_name: str
    guild_name: str
    norm_score_ex_h: float
    heuristic_prob: int
    prototype_prob: int
    display_prob: int
    sources_label: str
    spring_peak: str
    autumn_peak: str


class CardEvaluator:
    def __init__(self, db_path: str, species_resolver: SpeciesResolver):
        self.db_path = db_path
        self.resolver = species_resolver

    @staticmethod
    def calculate_peak_period_string(day_counts: List[Dict[str, Any]]) -> str:
        """
        Berekent de piekperiode (startday - endday op 50% van de dagpiek) voor een lijst van dag-counts.
        """
        if not day_counts:
            return "geen"

        max_row = max(day_counts, key=lambda x: float(x.get("count", 0)))
        max_count = float(max_row.get("count", 0))

        if max_count <= 0:
            return "geen"

        threshold = max_count * 0.5
        peak_days = [int(r.get("day", 0)) for r in day_counts if float(r.get("count", 0)) >= threshold]

        if not peak_days:
            return "geen"

        start_day = min(peak_days)
        end_day = max(peak_days)

        dt_start = datetime.strptime(f"2026-{start_day}", "%Y-%j")
        dt_end = datetime.strptime(f"2026-{end_day}", "%Y-%j")

        fmt_start = dt_start.strftime("%d %b").lower()
        fmt_end = dt_end.strftime("%d %b").lower()

        if start_day == end_day:
            return fmt_start
        else:
            return f"{fmt_start} - {fmt_end}"

    def get_species_historical_peaks(self, soort_id: str, site_ids: List[str]) -> Tuple[str, str]:
        """
        Haalt de dag-distributie op uit SQLite en berekent de voorjaars- en najaars-piek.
        """
        query = """
            SELECT 
                CAST(strftime('%j', datetime(CAST(h.begintijd AS INTEGER), 'unixepoch')) AS INTEGER) as day,
                SUM(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER)) as count
            FROM waarnemingen w
            INNER JOIN telling_headers h ON w.tellingid = h.tellingid
            WHERE w.soortid = ? AND (h.telpostid IN ({seq}))
            GROUP BY day
        """.format(seq=','.join(['?'] * len(site_ids)) if site_ids else "''")

        params = [soort_id] + site_ids

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                rows = [dict(r) for r in cursor.execute(query, params).fetchall()]

                spring_days = [r for r in rows if int(r.get("day", 0)) <= 166]
                autumn_days = [r for r in rows if int(r.get("day", 0)) > 166]

                spring_peak = self.calculate_peak_period_string(spring_days)
                autumn_peak = self.calculate_peak_period_string(autumn_days)

                return spring_peak, autumn_peak
        except Exception as e:
            print(f"[CardEvaluator] Fout bij berekenen historische pieken: {e}")
            return "geen", "geen"

    def build_comparative_card(
        self,
        heuristic_s: Optional[VogelSuggestie],
        prototype_s: Optional[VogelSuggestie],
        site_ids: List[str]
    ) -> Optional[ComparativeCardData]:
        """
        Bouwt de complete vergelijkende CardView dataset voor een soort.
        """
        primary = prototype_s or heuristic_s
        if not primary:
            return None

        h_prob = heuristic_s.kans if heuristic_s else 0
        p_prob = prototype_s.kans if prototype_s else 0
        max_prob = max(h_prob, p_prob)

        sources = []
        if heuristic_s: sources.append("Heuristiek")
        if prototype_s: sources.append("Prototype")
        sources_str = " / ".join(sources)

        spring_peak, autumn_peak = self.get_species_historical_peaks(primary.soortid, site_ids)

        return ComparativeCardData(
            soortid=primary.soortid,
            soortnaam=primary.soortnaam,
            latin_name=primary.latin_name,
            guild_name=primary.guild_name,
            norm_score_ex_h=primary.expected_index,
            heuristic_prob=h_prob,
            prototype_prob=p_prob,
            display_prob=max_prob,
            sources_label=f"Bronnen: {sources_str}",
            spring_peak=spring_peak,
            autumn_peak=autumn_peak
        )