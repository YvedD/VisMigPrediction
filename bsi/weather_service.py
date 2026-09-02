"""
bsi/weather_service.py
Weer-integratie via Open-Meteo REST API's.
"""

import math
import requests
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, List


@dataclass
class WeatherContext:
    lat: float
    lon: float
    temp: Optional[float]
    wind_speed: Optional[float]
    wind_deg: Optional[float]
    cloud_percent: Optional[float]
    pressure: Optional[float]
    visibility: Optional[int]
    pressure_trend: Optional[float] = None


class WeatherManagerUtils:
    @staticmethod
    def ms_to_beaufort(ms: float) -> int:
        if ms < 0.3:
            return 0
        elif ms < 1.6:
            return 1
        elif ms < 3.4:
            return 2
        elif ms < 5.5:
            return 3
        elif ms < 8.0:
            return 4
        elif ms < 10.8:
            return 5
        elif ms < 13.9:
            return 6
        elif ms < 17.2:
            return 7
        elif ms < 20.8:
            return 8
        elif ms < 24.5:
            return 9
        elif ms < 28.5:
            return 10
        elif ms < 32.7:
            return 11
        else:
            return 12

    @staticmethod
    def deg_to_16_wind_label(deg: Optional[float]) -> str:
        if deg is None:
            return ""
        labels = ["N", "NNO", "NO", "ONO", "O", "OZO", "ZO", "ZZO", "Z", "ZZW", "ZW", "WZW", "W", "WNW", "NW", "NNW"]
        idx = int(round(deg / 22.5)) % 16
        return labels[idx]


class AiWeatherService:
    @staticmethod
    def fetch_contextual_weather(lat: float, lon: float) -> Optional[WeatherContext]:
        """
        Haalt het actuele weer op via Open-Meteo inclusief de 6-uurs luchtdruktrend.
        """
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,wind_speed_10m,wind_direction_10m,cloud_cover,surface_pressure,visibility&hourly=pressure_msl&past_days=1&forecast_days=1&wind_speed_unit=ms"
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return None

            data = resp.json()
            curr = data.get("current", {})

            # Luchtdruk trend (nu minus 6 uur geleden)
            pressure_trend = None
            hourly_p = data.get("hourly", {}).get("pressure_msl", [])
            if len(hourly_p) >= 24:
                curr_p = hourly_p[-1]
                past_p = hourly_p[-7] if len(hourly_p) >= 7 else hourly_p[0]
                if curr_p is not None and past_p is not None:
                    pressure_trend = curr_p - past_p

            return WeatherContext(
                lat=lat,
                lon=lon,
                temp=curr.get("temperature_2m"),
                wind_speed=curr.get("wind_speed_10m"),
                wind_deg=curr.get("wind_direction_10m"),
                cloud_percent=curr.get("cloud_cover"),
                pressure=curr.get("surface_pressure"),
                visibility=int(curr.get("visibility", 10000)),
                pressure_trend=pressure_trend
            )
        except Exception as e:
            print(f"[WeatherService] Fout bij ophalen weer: {e}")
            return None