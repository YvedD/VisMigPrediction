"""
bsi/solar_engine.py
Berekent biologische dagsegmenten op basis van de zonnestand.
"""

import math
from datetime import datetime
from enum import Enum


class SolarPhase(Enum):
    NIGHT = "Nacht"
    DAWN = "Vroege Ochtend"
    MORNING = "Ochtend"
    MIDDAY = "Middag"
    LATE_AFTERNOON = "Namiddag"
    EVENING = "Avond"


class SolarTimeEngine:
    @staticmethod
    def get_solar_phase(lat: float, lon: float, dt: datetime) -> SolarPhase:
        day_of_year = dt.timetuple().tm_yday
        hour_fraction = dt.hour + dt.minute / 60.0 + dt.second / 3600.0

        decl = 0.409 * math.sin(2.0 * math.pi * (day_of_year - 81) / 365.0)
        lat_rad = math.radians(lat)
        tan_val = -math.tan(lat_rad) * math.tan(decl)
        tan_val = max(-1.0, min(1.0, tan_val))
        hour_angle = math.acos(tan_val)
        day_length_hours = (2.0 * math.degrees(hour_angle)) / 15.0

        tz_offset = dt.utcoffset().total_seconds() / 3600.0 if dt.utcoffset() else 0.0
        solar_noon = 12.0 - (lon / 15.0) + tz_offset

        sunrise = solar_noon - (day_length_hours / 2.0)
        sunset = solar_noon + (day_length_hours / 2.0)

        if hour_fraction < sunrise - 1.0 or hour_fraction > sunset + 1.5:
            return SolarPhase.NIGHT
        elif hour_fraction < sunrise + 1.0:
            return SolarPhase.DAWN
        elif hour_fraction < solar_noon:
            return SolarPhase.MORNING
        elif hour_fraction < sunset - 3.0:
            return SolarPhase.MIDDAY
        elif hour_fraction < sunset:
            return SolarPhase.LATE_AFTERNOON
        else:
            return SolarPhase.EVENING