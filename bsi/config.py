"""
bsi/config.py
Centrale configuratie voor de BSI 4.1 prognose-engine.
"""

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class RefPoint:
    name: str
    lat: float
    lon: float


class BsiConfig:
    # 21 Strategische locaties voor najaar- en voorjaarstrek
    REFERENCE_POINTS: List[RefPoint] = [
        RefPoint("Falsterbo (SE)", 55.38, 12.83),
        RefPoint("Skagen (DK)", 57.72, 10.58),
        RefPoint("Blåvand (DK)", 55.55, 8.08),
        RefPoint("Helgoland (DE)", 54.18, 7.88),
        RefPoint("Sylt (DE)", 54.91, 8.30),
        RefPoint("Borkum (DE)", 53.58, 6.66),
        RefPoint("Texel (NL)", 53.05, 4.80),
        RefPoint("Lauwersmeer (NL)", 53.38, 6.19),
        RefPoint("IJmuiden (NL)", 52.46, 4.56),
        RefPoint("Gdansk (PL)", 54.35, 18.64),
        RefPoint("Cap Gris-Nez (FR)", 50.87, 1.58),
        RefPoint("Baie de Somme (FR)", 50.21, 1.62),
        RefPoint("Ouistreham (FR)", 49.28, -0.25),
        RefPoint("Île d'Oléron (FR)", 45.91, -1.30),
        RefPoint("Biarritz (FR)", 43.48, -1.56),
        RefPoint("Tarifa (ES)", 36.01, -5.60),
        RefPoint("Gibraltar (UK)", 36.14, -5.35),
        RefPoint("Sagres (PT)", 37.01, -8.94),
        RefPoint("Camargue (FR)", 43.53, 4.65),
        RefPoint("Mallorca (ES)", 39.69, 3.01),
        RefPoint("Messina (IT)", 38.19, 15.55)
    ]

    # BSI Drempels & BoI Floating Windows
    BOI_THRESHOLD_OBSERVATIONS: int = 50
    BOI_FLOATING_WINDOW_DAYS: int = 9
    NORMAL_FLOATING_WINDOW_DAYS: int = 7

    WIND_TOLERANCE_DEGREES: float = 12.0
    IS_COASTAL_SITE: bool = False
    MIN_BSI_QUALITY_THRESHOLD: int = 15
    EFFICIENCY_BOOST_PELAGIC_BFT: int = 5

    # Instelbare straffactor voor aanlandige wind aan de kust (verzacht de harde 90% blokkade)
    COASTAL_ONSHORE_PENALTY: float = 0.5

    USE_NEURAL_INFERENCE: bool = True
    NEURAL_INTEGRATION_WEIGHT: float = 0.5