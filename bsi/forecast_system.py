"""
bsi/forecast_system.py
Orchestratie van de 5-daagse (120-uurs) BSI vogelprognose inclusief Europese corridors.
"""

import math
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from .config import BsiConfig
from .weather_service import WeatherContext, WeatherManagerUtils
from .inference_engine import AiInferenceEngine, VogelSuggestie
from .solar_engine import SolarTimeEngine
from .species_resolver import SpeciesResolver
from .corridor_engine import CorridorEngine


@dataclass
class DailyForecastResult:
    date_str: str
    display_date: str
    weather_summary: str
    corridor_boost: float
    temp: float
    wind_bft: int
    wind_label: str
    top_species: List[VogelSuggestie]


class BsiForecastSystem:
    def __init__(self, db_path: str, species_resolver: SpeciesResolver):
        self.db_path = db_path
        self.resolver = species_resolver

    def fetch_5day_weather_forecast(self, lat: float, lon: float) -> Optional[List[Dict[str, Any]]]:
        """
        Haalt de 5-daagse uursvoorspelling op via Open-Meteo.
        """
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,surface_pressure,cloud_cover"
            f"&wind_speed_unit=ms&forecast_days=5&timezone=auto"
        )
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json()
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])

            result = []
            for i in range(len(times)):
                result.append({
                    "time": times[i],
                    "temp": hourly.get("temperature_2m", [])[i],
                    "wind_speed": hourly.get("wind_speed_10m", [])[i],
                    "wind_deg": hourly.get("wind_direction_10m", [])[i],
                    "pressure": hourly.get("surface_pressure", [])[i],
                    "cloud_cover": hourly.get("cloud_cover", [])[i]
                })
            return result
        except Exception as e:
            print(f"[ForecastSystem] Fout bij ophalen 5d forecast: {e}")
            return None

    def generate_5day_prognosis(
        self,
        lat: float,
        lon: float,
        site_ids: List[str],
        start_dt: Optional[datetime] = None
    ) -> List[DailyForecastResult]:
        """
        Genereert de volledige 5-daagse BSI vogelprognose inclusief corridor-boosts.
        """
        if start_dt is None:
            start_dt = datetime.now(timezone.utc)

        # 1. Bepaal seizoenscorridor (Najaar: Juli t/m Nov = maanden 7-11)
        current_month = start_dt.month
        is_autumn = 7 <= current_month <= 11

        # Haal weerbericht op voor telpost (5 dagen) en de 6 corridor punten
        hourly_weather = self.fetch_5day_weather_forecast(lat, lon)
        corridor_data = CorridorEngine.fetch_corridor_forecasts(is_autumn=is_autumn)

        if not hourly_weather:
            return []

        # Filter op de 10:00u ijkmomenten voor de 5 opeenvolgende dagen
        daily_snapshots = [h for h in hourly_weather if h["time"].endswith("T10:00") or h["time"].endswith(" 10:00")]
        if not daily_snapshots:
            # Fallback op index-sprongen van 24 uur (24, 48, 72, 96, 120)
            daily_snapshots = [hourly_weather[i] for i in [10, 34, 58, 82, 106] if i < len(hourly_weather)]

        results: List[DailyForecastResult] = []

        for snapshot in daily_snapshots:
            time_str = snapshot["time"]
            dt_day = datetime.fromisoformat(time_str.replace("Z", "+00:00")) if "T" in time_str else datetime.strptime(time_str, "%Y-%m-%d %H:%M")

            day_of_year = dt_day.timetuple().tm_yday
            window_size = BsiConfig.BOI_FLOATING_WINDOW_DAYS
            day_start = day_of_year - (window_size // 2)
            day_end = day_of_year + (window_size // 2)

            species_profiles = self._fetch_phenology_profiles_from_db(day_start, day_end, site_ids)
            if not species_profiles:
                continue

            w_ctx = WeatherContext(
                lat=lat,
                lon=lon,
                temp=snapshot.get("temp"),
                wind_speed=snapshot.get("wind_speed"),
                wind_deg=snapshot.get("wind_deg"),
                cloud_percent=snapshot.get("cloud_cover"),
                pressure=snapshot.get("pressure"),
                visibility=10000,
                pressure_trend=0.0
            )

            # Bereken stroomopwaartse corridor boost (regBoost) voor dit tijdstip
            reg_boost = CorridorEngine.calculate_corridor_boost_at_time(dt_day, corridor_data, is_autumn=is_autumn)

            baseline_suggesties = AiInferenceEngine.calculate_bsi_prognosis(
                lat=lat, lon=lon, dt=dt_day, weather=w_ctx,
                species_profiles=species_profiles, neural_engine=None
            )
            baseline_map = {s.soortid: s for s in baseline_suggesties}

            combined_list = []
            for sid, s_obj in baseline_map.items():
                s_obj.latin_name = self.resolver.get_latin(sid)
                # Pas de corridor boost toe op de score en kans
                s_obj.score *= (1.0 + reg_boost)
                s_obj.kans = int(min(98, s_obj.kans * (1.0 + (reg_boost * 0.5))))
                combined_list.append(s_obj)

            top_10 = sorted(combined_list, key=lambda x: (x.kans, x.score), reverse=True)[:10]

            bft = WeatherManagerUtils.ms_to_beaufort(snapshot.get("wind_speed", 0.0))
            wind_lbl = WeatherManagerUtils.deg_to_16_wind_label(snapshot.get("wind_deg"))
            temp_c = round(snapshot.get("temp", 0.0), 1)
            summary = f"Wind: {wind_lbl} {bft}Bft | Temp: {temp_c}°C"

            results.append(DailyForecastResult(
                date_str=dt_day.strftime("%Y-%m-%d"),
                display_date=dt_day.strftime("%A %d %B").capitalize(),
                weather_summary=summary,
                corridor_boost=reg_boost,
                temp=temp_c,
                wind_bft=bft,
                wind_label=wind_lbl,
                top_species=top_10
            ))

        return results

    def _fetch_phenology_profiles_from_db(self, day_start: int, day_end: int, site_ids: List[str]) -> List[Dict[str, Any]]:
        import sqlite3
        query = """
            SELECT 
                w.soortid, 
                SUM(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER) + CAST(w.aantal_plus AS INTEGER) + CAST(w.aantalterug_plus AS INTEGER)) as count,
                AVG(CAST(NULLIF(h.temperatuur, '') AS FLOAT)) as avgTemp,
                UPPER(h.windrichting) as mainWind,
                AVG(CAST(NULLIF(h.windkracht, '') AS FLOAT)) as avgBft,
                AVG(CAST(NULLIF(h.hpa, '') AS FLOAT)) as avgPressure,
                AVG(CAST(strftime('%H', datetime(CAST(MAX(w.tijdstip, h.begintijd) AS INTEGER), 'unixepoch', 'localtime')) AS INTEGER)) as avgHour,
                MAX(CAST(w.markeren AS INTEGER)) as isRemarkable
            FROM waarnemingen w
            INNER JOIN telling_headers h ON w.tellingid = h.tellingid
            WHERE ((CAST(strftime('%j', datetime(CAST(h.begintijd AS INTEGER), 'unixepoch')) AS INTEGER) BETWEEN ? AND ?)
               OR (CAST(strftime('%j', datetime(CAST(h.begintijd AS INTEGER), 'unixepoch')) AS INTEGER) + 365 BETWEEN ? AND ?)
               OR (CAST(strftime('%j', datetime(CAST(h.begintijd AS INTEGER), 'unixepoch')) AS INTEGER) - 365 BETWEEN ? AND ?))
               AND (h.telpostid IN ({seq}))
               AND h.telpostid != '5177'
            GROUP BY w.soortid
            ORDER BY count DESC
            LIMIT 100
        """.format(seq=','.join(['?'] * len(site_ids)) if site_ids else "''")

        params = [day_start, day_end, day_start, day_end, day_start, day_end] + site_ids

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                rows = cursor.execute(query, params).fetchall()
                results = []
                for r in rows:
                    d = dict(r)
                    d["soortnaam"] = self.resolver.get_name(d["soortid"])
                    d["latin"] = self.resolver.get_latin(d["soortid"])
                    d["expectedIndex"] = float(d["count"]) / 100.0
                    results.append(d)
                return results
        except Exception as e:
            print(f"[ForecastSystem] SQLite query fout: {e}")
            return []