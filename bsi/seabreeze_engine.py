"""
bsi/seabreeze_engine.py
Berekent de Zeebries-factor (Sea Breeze Front effect) voor land- en zangvogels
langs de kust en tot 6 km landinwaarts gedurende warme, zonnige middagen.
"""

from datetime import datetime
from typing import Optional
from .config import BsiConfig


class SeaBreezeEngine:
    @staticmethod
    def get_seabreeze_multiplier(
            dt: datetime,
            temp: Optional[float],
            cloud_percent: Optional[float],
            wind_speed: Optional[float],
            is_coastal: bool
    ) -> float:
        """
        Berekent de correctiefactor op basis van zeebries dynamica.
        - Ontstaat bij: zonnig (weinig bewolking), warme middag (12:00 - 18:00), zwakke basiswind (< 4.5 m/s).
        - Effect op kusttelposten: Concentratie-boost voor landvogels die langs de kust opstapelen.
        - Effect op landinwaarts (5-6 km): Remmende motor / dip in landvogeltrek door koude zeeluchtfront.
        """
        hour = dt.hour
        # Zeebries treedt met name op in de middag (12:00 tot 18:00 lokale tijd)
        if not (12 <= hour <= 18):
            return 1.0

        t = temp if temp is not None else 15.0
        cloud = cloud_percent if cloud_percent is not None else 50.0
        ws = wind_speed if wind_speed is not None else 5.0

        # Voorwaarden voor thermische zeebries: warm (> 18°C), zonnig (< 40% bewolking), zwakke basiswind (< 4.5 m/s)
        if t >= 18.0 and cloud <= 40.0 and ws <= 4.5:
            if is_coastal:
                # Kusttelpost: vogels hopen zich op tegen de zeebriesgrens -> lichte boost
                return 1.25
            else:
                # Landinwaarts (5-6 km): koelere zeelucht remt de trek af -> straf/dip
                return 0.65

        return 1.0