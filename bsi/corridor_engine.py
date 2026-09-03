"""
bsi/corridor_engine.py
Beheert stroomopwaartse Europese corridors (bijv. Scandinavië / Baltische Staten)
en berekent corridor-boosts op basis van weersomstandigheden en windstroom.
"""

import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional


class CorridorEngine:
    # Coördinaten van belangrijke stroomopwaartse migratiecorridors in Noord-/Oost-Europa
    CORRIDOR_POINTS = [
        {"name": "Zuid-Zweden (Falsterbo)", "lat": 55.38, "lon": 12.82},
        {"name": "Denemarken (Skagen)", "lat": 57.73, "lon": 10.58},
        {"name": "Noord-Duitsland (Elbe)", "lat": 53.55, "lon": 9.99},
        {"name": "Baltische Kust (Kurland)", "lat": 57.35, "lon": 21.55},
        {"name": "Oost-Nederland (Lauwersmeer)", "lat": 53.35, "lon": 6.20},
        {"name": "Noord-Frankrijk (Cap Gris-Nez)", "lat": 50.87, "lon": 1.58}
    ]

    @classmethod
    def fetch_corridor_forecasts(cls, is_autumn: bool = True) -> List[Dict[str, Any]]:
        """
        Haalt weersvoorspellingen op voor alle corridor-punten via Open-Meteo.
        """
        corridor_results = []
        for point in cls.CORRIDOR_POINTS:
            url = (
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={point['lat']}&longitude={point['lon']}"
                f"&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,surface_pressure,cloud_cover"
                f"&wind_speed_unit=ms&forecast_days=5&timezone=auto"
            )
            try:
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    hourly = data.get("hourly", {})
                    corridor_results.append({
                        "name": point["name"],
                        "hourly": hourly
                    })
            except Exception as e:
                print(f"[CorridorEngine] Kon data niet ophalen voor {point['name']}: {e}")
        return corridor_results

    @classmethod
    def calculate_corridor_boost_at_time(
        cls,
        target_dt: datetime,
        corridor_data: List[Dict[str, Any]],
        is_autumn: bool = True
    ) -> float:
        """
        Berekent de stroomopwaartse corridor boost op een specifiek tijdstip.
        Vergelijkt datums veilig zonder timezone-conflicten.
      """
        if not corridor_data:
            return 0.0

        # Maak target_dt timezone-naive voor veilige vergelijking
        target_naive = target_dt.replace(tzinfo=None)
        total_score = 0.0
        count = 0

        for point in corridor_data:
            hourly = point.get("hourly", {})
            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            wind_speeds = hourly.get("wind_speed_10m", [])
            wind_degs = hourly.get("wind_direction_10m", [])
            pressures = hourly.get("surface_pressure", [])

            for i, time_str in enumerate(times):
                try:
                    # Parse corridor tijdstip en maak ook dit timezone-naive
                    if "T" in time_str:
                        dt_entry = datetime.fromisoformat(time_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    else:
                        dt_entry = datetime.strptime(time_str, "%Y-%m-%d %H:%M").replace(tzinfo=None)

                    # Match binnen een venster van 2 uur
                    if abs((dt_entry - target_naive).total_seconds()) <= 7200:
                        score = cls.calculate_single_point_score(
                            wind_deg=wind_degs[i] if i < len(wind_degs) else 0.0,
                            pressure_hpa=pressures[i] if i < len(pressures) else 1013.0,
                            temp=temps[i] if i < len(temps) else 15.0,
                            wind_speed=wind_speeds[i] if i < len(wind_speeds) else 5.0,
                            is_autumn=is_autumn
                        )
                        total_score += score
                        count += 1
                        break
                except Exception:
                    continue

        if count == 0:
            return 0.0

        avg_score = total_score / count
        # Normaliseer naar een boost factor tussen 0.0 en 0.40 (+40% max boost)
        return min(0.40, max(0.0, avg_score * 0.15))

    @staticmethod
    def calculate_single_point_score(
        wind_deg: float,
        pressure_hpa: float,
        temp: float,
        wind_speed: float,
        is_autumn: bool
    ) -> float:
        score = 1.0
        # In najaar helpt rugwind uit het noordoosten/oosten (40°-90°)
        if is_autumn:
            if 30 <= wind_deg <= 110:
                score += 1.2
        else:  # Voorjaar: rugwind vanuit zuid/zuidwest (180°-240°)
            if 160 <= wind_deg <= 260:
                score += 1.2

        # Hoge druk achter de rug stimuleert vertrek
        if pressure_hpa > 1016:
            score += 0.5

        return score