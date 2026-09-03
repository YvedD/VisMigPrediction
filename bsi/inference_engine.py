"""
bsi/inference_engine.py
De master BSI 4.1 voorspellingsmotor (Fijnafgesteld met storm-, kust- en zeebriesoptimalisatie).
"""

import math
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional, Any

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


class AiInferenceEngine:
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
        """
        Berekent de volledige BSI 4.1 prognose voor een gegeven tijdstip en locatie.
        """
        epoch_sec = int(dt.timestamp())
        phase = SolarTimeEngine.get_solar_phase(lat, lon, dt)
        current_hour = dt.hour
        current_temp = weather.temp if weather.temp is not None else 15.0
        current_wind_deg = weather.wind_deg if weather.wind_deg is not None else 0.0
        current_wind_label = WeatherManagerUtils.deg_to_16_wind_label(current_wind_deg)
        bft = WeatherManagerUtils.ms_to_beaufort(weather.wind_speed if weather.wind_speed is not None else 0.0)

        # Neuraal netwerk voorwaartse pass
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
                precipitation_flag=False
            )
            neural_predictions = neural_engine.predict(features)

        scored_species: List[VogelSuggestie] = []

        # FINETUNING: Noemer verlaagd van 5.0 naar 3.0 voor betere percentages
        ideal_score = 3.0

        for p in species_profiles:
            soortid = p["soortid"]
            name = p["soortnaam"]
            latin = p.get("latin", "")

            if "spec." in name.lower() or "onbekend" in name.lower() or "/" in name:
                continue

            guild = SpeciesGuildMapper.get_guild_by_latin(latin)
            if guild == Guild.OTHER:
                continue

            strategy = guild.strategy

            # F1: Massa (Log)
            f_massa_raw = math.log10(max(1.0, float(p.get("count", 1))))
            f_massa = 1.0 + (f_massa_raw * 0.4)

            # FINETUNING: Efficiency Ratio ondergrens verhoogd van 0.01 naar 0.25
            best_count = float(p.get("bestWindCount", 1))
            curr_count = float(p.get("currentWindCount", 0))
            efficiency_ratio = max(0.25, min(1.0, curr_count / (best_count if best_count > 0 else 1.0)))

            # F2: Wind-DNA (met de nieuwe 12° tolerantie)
            hist_wind_deg = TrainingDataPreparer.parse_wind_direction_to_degrees(p.get("mainWind")) or current_wind_deg
            diff = abs(current_wind_deg - hist_wind_deg)
            normalized_diff = 360.0 - diff if diff > 180 else diff

            if normalized_diff <= BsiConfig.WIND_TOLERANCE_DEGREES:
                f_wind = 1.8
            else:
                f_wind = max(0.1, 1.8 * math.exp(-(normalized_diff ** 2) / 400.0))

            # F3: Special / Krenten
            f_special = 1.0
            is_krent = expert_kb and (soortid in expert_kb.discovered_krenten or soortid in expert_kb.pinned_species)
            if p.get("isRemarkable") == 1:
                f_special = 4.5
            elif is_krent:
                f_special = 3.0

            # F4: Tijd & Strategie
            f_time = 1.0
            target_hour = float(p.get("avgHour", 10.0))
            hour_diff = abs(current_hour - target_hour)

            if strategy == FlightStrategy.THERMAL:
                if current_hour < 9 or current_hour > 18 or phase == SolarPhase.NIGHT or bft >= 6:
                    f_time = 0.0001
                else:
                    f_time = 0.5 + (max(0.1, min(10.0, current_temp - 10.0)) / 10.0)

            elif strategy == FlightStrategy.ACTIVE:
                if phase == SolarPhase.NIGHT and guild != Guild.PELAGICS:
                    f_time = 0.01
                else:
                    f_time = math.exp(-(hour_diff ** 2) / 40.0)

            elif strategy == FlightStrategy.VISMIG:
                if phase == SolarPhase.NIGHT:
                    f_time = 0.0001
                else:
                    f_time = math.exp(-(hour_diff ** 2) / 25.0)

            # F5: Local Wind Gatekeeper & Data-Driven Storm Boost
            f_gatekeeper = 1.0
            is_off_shore = current_wind_label in {"O", "OZO", "ZO", "ZZO", "Z"}
            is_on_shore = current_wind_label in {"NW", "WNW", "W", "ZW", "NNW"}

            # Controleer of er historische stormdata beschikbaar is voor deze soort bij deze wind
            storm_bonus_multiplier = 1.0
            if 'storm_df' in p and not p['storm_df'].empty:
                match_storm = p['storm_df'][
                    (p['storm_df']['soortid'] == soortid) &
                    (p['storm_df']['wind_richting'] == current_wind_label) &
                    (p['storm_df']['wind_bft'] >= bft)
                ]
                if not match_storm.empty:
                    totaal_historisch = match_storm['totaal_aantal'].sum()
                    storm_bonus_multiplier = 1.0 + min(2.0, math.log10(max(10.0, totaal_historisch)) * 0.4)

            if guild == Guild.PELAGICS:
                if is_off_shore:
                    f_gatekeeper = 0.001
                elif is_on_shore:
                    base_pelagic_boost = 2.0 * (1.0 + (bft - 4) * 0.5) if bft >= BsiConfig.EFFICIENCY_BOOST_PELAGIC_BFT else 2.0
                    f_gatekeeper = base_pelagic_boost * storm_bonus_multiplier

            elif guild in {Guild.RAPTORS_ACTIVE, Guild.RAPTORS_THERMAL, Guild.PASSERINES, Guild.HERONS}:
                if BsiConfig.IS_COASTAL_SITE and is_on_shore:
                    f_gatekeeper = 0.5 if bft >= 4 else 0.8
                elif current_wind_label in {"O", "ONO", "NO"}:
                    f_gatekeeper = 1.5 * storm_bonus_multiplier

            # Zeebries-remmingsfactor / concentratie-boost voor land- en zangvogels in de middag
            seabreeze_factor = 1.0
            if guild in {Guild.PASSERINES, Guild.LANDBIRDS_REG, Guild.LANDBIRDS_SPECIAL}:
                seabreeze_factor = SeaBreezeEngine.get_seabreeze_multiplier(
                    dt=dt,
                    temp=weather.temp,
                    cloud_percent=weather.cloud_percent,
                    wind_speed=weather.wind_speed,
                    is_coastal=BsiConfig.IS_COASTAL_SITE
                )

            # Aggregatie van BSI Score inclusief zeebries-dynamica
            total_score = f_massa * f_wind * f_special * f_time * f_gatekeeper * efficiency_ratio * seabreeze_factor

            # Neurale Boost
            if neural_predictions is not None and model_labels and soortid in model_labels:
                idx = model_labels.index(soortid)
                if 0 <= idx < len(neural_predictions):
                    prob = float(neural_predictions[idx])
                    total_score *= (1.0 + BsiConfig.NEURAL_INTEGRATION_WEIGHT * prob)

            # Percentage omzetting (max 98%)
            prob_raw = int(min(0.98, total_score / ideal_score) * 100)

            if prob_raw >= BsiConfig.MIN_BSI_QUALITY_THRESHOLD:
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