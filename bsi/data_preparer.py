"""
bsi/data_preparer.py
Feature Engineering module. Converteert context naar een 21-elementen vector.
"""

import math
import numpy as np
from datetime import datetime, timezone
from typing import Optional


class TrainingDataPreparer:
    @staticmethod
    def calculate_moon_phase(epoch_sec: int) -> float:
        """
        Berekent de maanfase (0.0 = Nieuwe Maan, 0.5 = Volle Maan, 1.0 = Nieuwe Maan).
        """
        known_new_moon_epoch = 1704974760  # 11 Jan 2024
        synodic_month_seconds = 29.530588 * 24 * 3600
        delta = epoch_sec - known_new_moon_epoch
        phase = (delta % synodic_month_seconds) / synodic_month_seconds
        return phase + 1.0 if phase < 0 else phase

    @staticmethod
    def parse_wind_direction_to_degrees(s: Optional[str]) -> Optional[float]:
        if not s or not s.strip():
            return None
        t = s.strip().upper().replace("°", "")
        try:
            return float(t)
        except ValueError:
            pass

        labels = ["N", "NNO", "NO", "ONO", "O", "OZO", "ZO", "ZZO", "Z", "ZZW", "ZW", "WZW", "W", "WNW", "NW", "NNW"]
        if t in labels:
            return labels.index(t) * 22.5

        eng = {
            "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5, "E": 90.0, "ESE": 112.5,
            "SE": 135.0, "SSE": 157.5, "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
            "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5
        }
        return eng.get(t)

    @classmethod
    def build_feature_vector_for_context(
        cls,
        epoch_sec: int,
        telpost_id: Optional[str] = None,
        temperature: Optional[float] = None,
        wind_deg: Optional[float] = None,
        wind_force: Optional[float] = None,
        cloud_cover: Optional[float] = None,
        hpa: Optional[float] = None,
        precipitation_flag: Optional[bool] = None
    ) -> np.ndarray:
        """
        Bouwt de gestandaardiseerde 21-elementen feature vector.
        """
        features = np.zeros(21, dtype=np.float32)
        dt = datetime.fromtimestamp(epoch_sec, tz=timezone.utc)

        day_of_year = dt.timetuple().tm_yday
        hour_of_day = dt.hour + dt.minute / 60.0

        # 0-3: Tijdstip circulariteit
        features[0] = math.sin(2.0 * math.pi * day_of_year / 365.25)
        features[1] = math.cos(2.0 * math.pi * day_of_year / 365.25)
        features[2] = math.sin(2.0 * math.pi * hour_of_day / 24.0)
        features[3] = math.cos(2.0 * math.pi * hour_of_day / 24.0)

        # 4-8: Basis Weer
        features[4] = temperature if temperature is not None else 15.0
        wdeg = wind_deg if wind_deg is not None else 0.0
        features[5] = math.sin(math.radians(wdeg))
        features[6] = math.cos(math.radians(wdeg))
        features[7] = wind_force if wind_force is not None else 0.0
        features[8] = (cloud_cover / 8.0) if cloud_cover is not None else 0.0

        # 9-10: Luchtdruk & Trend
        features[9] = hpa if hpa is not None else 1013.0
        features[10] = 0.0

        # 11: Gisteren factor
        features[11] = 0.0

        # 12: Maanfase
        features[12] = cls.calculate_moon_phase(epoch_sec)

        # 13: Neerslag vlag
        features[13] = 1.0 if precipitation_flag else 0.0

        # 14: Telpost Hash
        telpost_hash = (abs(hash(telpost_id)) % 1000) if telpost_id else 0
        features[14] = telpost_hash / 1000.0

        return features