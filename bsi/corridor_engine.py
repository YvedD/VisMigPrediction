"""
bsi/corridor_engine.py
Berekent de Europese Corridor Boost voor meerdaagse BSI vogelprognoses.
"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any
from .config import BsiConfig
from .weather_service import WeatherManagerUtils


class CorridorEngine:
    @staticmethod
    def calculate_single_point_score(wind_deg: float, pressure_hpa: float, is_autumn: bool) -> float:
        """
        Beoordeelt of een enkel corridor-punt op een specifiek uur ideale vertrekcondities heeft.
        """
        wind_label = WeatherManagerUtils.deg_to_16_wind_label(wind_deg)
        p = pressure_hpa if pressure_hpa is not None else 1013.0

        if is_autumn:
            # Najaar: Rugwind uit N, NNO, NO, ONO, O en Hoge Luchtdruk (> 1014 hPa)
            if wind_label in ["N", "NNO", "NO", "ONO", "O"] and p > 1014.0:
                return 1.0
            return 0.0
        else:
            # Voorjaar: Rugwind uit Z, ZZW, ZW, WZW en Goede Luchtdruk (> 1010 hPa)
            if wind_label in ["Z", "ZZW", "ZW", "WZW"] and p > 1010.0:
                return 1.0
            return 0.0

    @classmethod
    def fetch_corridor_forecasts(cls, is_autumn: bool) -> Dict[str, List[Dict[str, Any]]]:
        """
        Haalt de 5-daagse weersvoorspelling op voor de 6 relevante corridor-punten via Open-Meteo.
        """
        ref_points = BsiConfig.REFERENCE_POINTS[:6] if is_autumn else BsiConfig.REFERENCE_POINTS[-6:]

        lats = ",".join(str(p.lat) for p in ref_points)
        lons = ",".join(str(p.lon) for p in ref_points)

        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lats}&longitude={lons}"
            f"&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,surface_pressure"
            f"&wind_speed_unit=ms&forecast_days=5&timezone=auto"
        )

        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return {}

            data = resp.json()
            data_list = data if isinstance(data, list) else [data]

            results: Dict[str, List[Dict[str, Any]]] = {}
            for i, p_data in enumerate(data_list):
                point_name = ref_points[i].name
                hourly = p_data.get("hourly", {})
                times = hourly.get("time", [])

                point_hours = []
                for j in range(len(times)):
                    point_hours.append({
                        "time": times[j],
                        "temp": hourly.get("temperature_2m", [])[j],
                        "wind_speed": hourly.get("wind_speed_10m", [])[j],
                        "wind_deg": hourly.get("wind_direction_10m", [])[j],
                        "pressure": hourly.get("surface_pressure", [])[j]
                    })
                results[point_name] = point_hours

            return results
        except Exception as e:
            print(f"[CorridorEngine] Fout bij ophalen corridor forecast: {e}")
            return {}

    @classmethod
    def calculate_corridor_boost_at_time(
            cls,
            target_dt: datetime,
            corridor_forecasts: Dict[str, List[Dict[str, Any]]],
            is_autumn: bool
    ) -> float:
        """
        Berekent de regBoost (0.0 tot 1.0) voor een specifiek voorspeld tijdstip op basis van stroomopwaartse wind.
        """
        if not corridor_forecasts:
            return 0.0

        total_max_score = 0.0

        for point_name, hourly_list in corridor_forecasts.items():
            window_start = target_dt - timedelta(hours=6)
            window_end = target_dt + timedelta(hours=1)

            best_in_window = 0.0

            for entry in hourly_list:
                time_str = entry["time"]
                dt_entry = datetime.fromisoformat(
                    time_str.replace("Z", "+00:00")) if "T" in time_str else datetime.strptime(time_str,
                                                                                               "%Y-%m-%d %H:%M")

                if window_start <= dt_entry <= window_end:
                    score = cls.calculate_single_point_score(
                        wind_deg=entry.get("wind_deg", 0.0),
                        pressure_hpa=entry.get("pressure", 1013.0),
                        is_autumn=is_autumn
                    )
                    if score > best_in_window:
                        best_in_window = score

            total_max_score += best_in_window

        return total_max_score / float(len(corridor_forecasts))