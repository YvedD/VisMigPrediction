"""
bsi/inference_engine.py
De master BSI 4.1 voorspellingsmotor met zachte wind-DNA voorkeuren,
database-brede fenologie-analyse, empirische wind-sector/maand/beaufort baseline,
aangepaste Pelagics-curve, en strikte ecologische remmen voor zangvogels (tijd- en windkracht).
"""

import math
import json
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

from app_paths import project_path
from .config import BsiConfig
from .solar_engine import SolarTimeEngine, SolarPhase
from .guild_mapper import SpeciesGuildMapper, FlightStrategy, Guild
from .weather_service import WeatherContext, WeatherManagerUtils
from .data_preparer import TrainingDataPreparer
from .neural_engine import LiteNeuralEngine
from .expert_knowledge import ExpertKnowledgeBase
from .seabreeze_engine import SeaBreezeEngine

@dataclass
class VogelSuggestie:
    soortid: str
    soortnaam: str
    latin_name: str
    kans: int
    guild_name: str
    expected_index: float
    score: float


def calculate_pelagic_factor(bft: float, wind_label: str) -> float:
    """
    Berekent de windfactor voor Pelagics (Zeevogels) op basis van windkracht én de verfijnde windrichtingsmatrix:
    - Lage wind geeft weinig extra ondersteuning, maar sluit soorten niet uit.
    - Ideale piekperiode / plateau: 6 tot 9 Beaufort.
    - Windrichting werkt als zachte voorkeur en niet als harde uitsluiting.
    """
    if bft < 2.0:
        bft_score = 0.25
    elif bft < 5.0:
        bft_score = 0.25 + (bft / 5.0) * 0.35
    elif bft <= 9.0:
        if bft < 6.0:
            bft_score = 0.6 + 0.4 * ((bft - 5.0) / 1.0)
        else:
            bft_score = 1.0
    else:
        bft_score = max(0.05, 1.0 - (bft - 9.0) * 0.4)

    label_upper = wind_label.strip().upper()
    if label_upper in {"NW"}:
        dir_score = 1.0
    elif label_upper in {"WNW", "NNW", "W", "N"}:
        dir_score = 0.75
    elif label_upper in {"ZW", "ZZW", "WZW", "NO", "NNO", "ONO"}:
        dir_score = 0.55
    else:
        dir_score = 0.45

    return max(0.12, bft_score * dir_score * 1.8)


class AiInferenceEngine:
    @staticmethod
    def _load_wind_sector_baseline() -> Dict[str, Any]:
        path = project_path("wind_sector_baseline.json")
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @classmethod
    def calculate_bsi_prognosis(
        cls,
        lat: float,
        lon: float,
        dt: datetime,
        weather: WeatherContext,
        species_profiles: List[Dict[str, Any]],
        neural_engine: Optional[LiteNeuralEngine] = None,
        model_labels: Optional[List[str]] = None,
        expert_kb: Optional[ExpertKnowledgeBase] = None
    ) -> List[VogelSuggestie]:
        epoch_sec = int(dt.timestamp())
        phase = SolarTimeEngine.get_solar_phase(lat, lon, dt)
        current_hour = dt.hour
        current_month_str = str(dt.month)
        current_temp = weather.temp if weather.temp is not None else 15.0
        current_wind_speed = weather.wind_speed if weather.wind_speed is not None else 0.0
        current_wind_deg = weather.wind_deg if weather.wind_deg is not None else 0.0
        current_wind_label = WeatherManagerUtils.deg_to_16_wind_label(current_wind_deg)
        bft = WeatherManagerUtils.ms_to_beaufort(current_wind_speed)
        precipitation_mm = getattr(weather, 'precipitation', 0.0) or 0.0

        if current_wind_speed <= 2.5:
            bft_class = "0-2 Bft"
        elif current_wind_speed <= 4.5:
            bft_class = "3-4 Bft"
        else:
            bft_class = "5+ Bft"

        baseline = cls._load_wind_sector_baseline()
        sector_baseline = baseline.get(current_wind_label, {})
        month_baseline = sector_baseline.get("maanden", {}).get(current_month_str, {})
        bft_baseline_soorten = month_baseline.get(bft_class, {}).get("soorten", {})

        neural_predictions = None
        if neural_engine and model_labels and BsiConfig.USE_NEURAL_INFERENCE:
            features = TrainingDataPreparer.build_feature_vector_for_context(
                epoch_sec=epoch_sec,
                telpost_id=None,
                temperature=weather.temp,
                wind_deg=weather.wind_deg,
                wind_force=weather.wind_speed,
                cloud_cover=weather.cloud_percent,
                hpa=weather.pressure,
                precipitation_flag=(precipitation_mm > 0.0)
            )
            neural_predictions = neural_engine.predict(features)

        scored_species: List[VogelSuggestie] = []
        ideal_score = 2.5

        for p in species_profiles:
            soortid = str(p["soortid"]).strip()
            name = p["soortnaam"]
            latin = p.get("latin", "")

            if "spec." in name.lower() or "onbekend" in name.lower() or "/" in name:
                continue

            guild = SpeciesGuildMapper.get_guild_by_latin(latin)
            if guild == Guild.OTHER:
                continue

            # F1: Massa (Log)
            f_massa_raw = math.log10(max(1.0, float(p.get("count", 1))))
            f_massa = 1.0 + (f_massa_raw * 0.3)

            # Efficiency Ratio
            best_count = float(p.get("bestWindCount", 1))
            curr_count = float(p.get("currentWindCount", 0))
            efficiency_ratio = max(0.35, min(1.0, curr_count / (best_count if best_count > 0 else 1.0)))

            # F2: zachte wind-DNA voorkeur; afwijkende historische wind sluit niet uit
            hist_wind_deg = TrainingDataPreparer.parse_wind_direction_to_degrees(p.get("mainWind")) or current_wind_deg
            diff = abs(current_wind_deg - hist_wind_deg)
            normalized_diff = 360.0 - diff if diff > 180 else diff

            f_wind = 0.9 + 0.8 * math.exp(-(normalized_diff ** 2) / 8100.0)

            # F3: Empirische Baseline Factor
            f_baseline = 1.0
            if soortid in bft_baseline_soorten:
                sp_stats = bft_baseline_soorten[soortid]
                freq_pct = float(sp_stats.get("frequentie_pct", 0.0))
                f_baseline = 1.0 + (freq_pct / 100.0) * 0.6

            # F4: Special / Krenten
            f_special = 1.0
            is_krent = expert_kb and (soortid in expert_kb.discovered_krenten or soortid in expert_kb.pinned_species)
            if p.get("isRemarkable") == 1:
                f_special = 4.0
            elif is_krent:
                f_special = 2.5

            # F5: Tijd & Strategie (Strikte afbouw voor zangvogels na 13:00 uur)
            f_time = 1.0
            target_hour = float(p.get("avgHour", 10.0))
            hour_diff = abs(current_hour - target_hour)

            if phase == SolarPhase.NIGHT and guild != Guild.PELAGICS:
                f_time = 0.02
            else:
                if guild == Guild.PASSERINES:
                    if current_hour > 13:
                        f_time = max(0.01, 0.4 * math.exp(-((current_hour - 11) ** 2) / 8.0))
                    else:
                        f_time = max(0.05, math.exp(-(hour_diff ** 2) / 30.0))
                else:
                    f_time = max(0.03, math.exp(-(hour_diff ** 2) / 35.0))

            # F6: Avond-rush factor (voor watervogels, reigers en lepelaars)
            f_evening_rush = 1.0
            is_lepelaar = ("lepelaar" in name.lower()) or ("platalea" in latin.lower())
            if 15 <= current_hour <= 19 and bft <= 4 and precipitation_mm < 0.2:
                if guild in {Guild.HERONS, Guild.WATERFOWL, Guild.SHOREBIRDS} or is_lepelaar:
                    f_evening_rush = 1.6

            # F7: Neerslag rem
            f_rain = 1.0
            if precipitation_mm > 0.1:
                f_rain = max(0.1, 1.0 - (precipitation_mm * 0.5))

            # F8: Gatekeeper & Windkracht rem voor Zangvogels (Passerines haten harde wind >= 4 Bft)
            f_gatekeeper = 1.0
            if guild == Guild.PELAGICS:
                f_gatekeeper = calculate_pelagic_factor(float(bft), current_wind_label)
            elif guild == Guild.PASSERINES:
                if bft >= 5:
                    f_gatekeeper = 0.15  # Zware straf bij 5 Bft of meer
                elif bft == 4:
                    f_gatekeeper = 0.45
                elif current_wind_label in {"ZW", "WZW", "W"} and 2 <= bft <= 3:
                    f_gatekeeper = 1.15
                else:
                    f_gatekeeper = 0.8
            elif guild in {Guild.RAPTORS_ACTIVE, Guild.RAPTORS_THERMAL, Guild.HERONS}:
                if current_wind_label in {"ZW", "WZW", "W"} and 2 <= bft <= 4:
                    f_gatekeeper = 1.25

            # Aggregatie van BSI Score
            total_score = f_massa * f_wind * f_baseline * f_special * f_time * f_evening_rush * f_rain * f_gatekeeper * efficiency_ratio

            # Neurale Boost
            if neural_predictions is not None and model_labels and soortid in model_labels:
                idx = model_labels.index(soortid)
                if 0 <= idx < len(neural_predictions):
                    prob = float(neural_predictions[idx])
                    total_score *= (1.0 + BsiConfig.NEURAL_INTEGRATION_WEIGHT * prob)

            prob_raw = int(min(0.98, total_score / ideal_score) * 100)

            minimum_threshold = BsiConfig.MIN_BSI_QUALITY_THRESHOLD
            if is_krent:
                minimum_threshold = min(minimum_threshold, 8)

            if prob_raw >= minimum_threshold:
                scored_species.append(VogelSuggestie(
                    soortid=soortid,
                    soortnaam=name,
                    latin_name=latin,
                    kans=prob_raw,
                    guild_name=guild.display_name,
                    expected_index=float(p.get("expectedIndex", 0.0)),
                    score=total_score
                ))

        return sorted(scored_species, key=lambda x: x.score, reverse=True)