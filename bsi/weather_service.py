"""
bsi/weather_service.py
Weer-integratie via Open-Meteo REST API's.
"""

import math
import requests
import streamlit as st
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
    # Definitieve 16-traps windroos intervals direct overgenomen uit 16-traps_windroos.txt
    _labels_intervals = [
        ("N", 348.75, 11.25),
        ("NNO", 11.25, 33.75),
        ("NO", 33.75, 56.25),
        ("ONO", 56.25, 78.75),
        ("O", 78.75, 101.25),
        ("OZO", 101.25, 123.75),
        ("ZO", 123.75, 146.25),
        ("ZZO", 146.25, 168.75),
        ("Z", 168.75, 191.25),
        ("ZZW", 191.25, 213.75),
        ("ZW", 213.75, 236.25),
        ("WZW", 236.25, 258.75),
        ("W", 258.75, 281.25),
        ("WNW", 281.25, 303.75),
        ("NW", 303.75, 326.25),
        ("NNW", 326.25, 348.75)
    ]

    @classmethod
    def _load_16_traps_mapping(cls):
        return cls._labels_intervals

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

    @classmethod
    def deg_to_16_wind_label(cls, deg: Optional[float]) -> str:
        if deg is None:
            return ""
        intervals = cls._load_16_traps_mapping()
        d = float(deg) % 360.0
        for label, start, end in intervals:
            s = float(start) % 360.0
            e = float(end) % 360.0
            if s <= e:
                if d >= s and d < e:
                    return label
            else:
                if d >= s or d < e:
                    return label

        # Fallback naar dichtstbijzijnde centrum
        centers = []
        for label, start, end in intervals:
            s = float(start) % 360.0
            e = float(end) % 360.0
            mid = ((s + ((e - s + 360.0) % 360.0) / 2.0) % 360.0)
            centers.append((label, mid))
        best = None
        best_dist = 360.0
        for label, center in centers:
            diff = abs(d - center) % 360.0
            diff = min(diff, 360.0 - diff)
            if diff < best_dist:
                best_dist = diff
                best = label
        return best if best is not None else ""

    @staticmethod
    def normalize_wind_label(label: Optional[str]) -> str:
        if not label:
            return ""
        return str(label).strip().upper()


class AiWeatherService:
    @staticmethod
    @st.cache_data(ttl=300)
    def fetch_contextual_weather(lat: float, lon: float) -> Optional[WeatherContext]:
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,wind_speed_10m,wind_direction_10m,cloud_cover,surface_pressure,visibility&hourly=pressure_msl&past_days=1&forecast_days=1&wind_speed_unit=ms"
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return None

            data = resp.json()
            curr = data.get("current", {})

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