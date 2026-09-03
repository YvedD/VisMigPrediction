"""
bsi/forecast_system.py
Orchestratie van de 5-daagse (120-uurs) en dagelijkse BSI vogelprognoses
inclusief Europese corridors, zonsopgang/ondergang en 2-uurlijkse tijdsblokken.
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


def calculate_sun_times(lat: float, lon: float, dt: datetime):
    """Berekent exact de zonsopgang en zonsondergang tijdstippen voor een locatie en datum."""
    day_of_year = dt.timetuple().tm_yday
    decl = 0.409 * math.sin(2.0 * math.pi * (day_of_year - 81) / 365.0)
    lat_rad = math.radians(lat)
    tan_val = -math.tan(lat_rad) * math.tan(decl)
    tan_val = max(-1.0, min(1.0, tan_val))
    hour_angle = math.acos(tan_val)
    day_length_hours = (2.0 * math.degrees(hour_angle)) / 15.0
    solar_noon = 12.0 - (lon / 15.0)

    sr_dec = solar_noon - (day_length_hours / 2.0)
    ss_dec = solar_noon + (day_length_hours / 2.0)

    sr_h = max(4, int(sr_dec))
    sr_m = int((sr_dec - sr_h) * 60)
    ss_h = min(22, int(ss_dec))
    ss_m = int((ss_dec - ss_h) * 60)

    return sr_h, ss_h, f"{sr_h:02d}:{sr_m:02d}", f"{ss_h:02d}:{ss_m:02d}"


@dataclass
class DailyForecastResult:
    date_str: str
    display_date: str
    weather_summary: str
    corridor_boost: float
    temp: float
    wind_bft: int
    wind_label: str
    wind_deg: float
    weather_trend: str
    sunrise: str
    sunset: str
    top_species: List[VogelSuggestie]


class BsiForecastSystem:
    def __init__(self, db_path: str, species_resolver: SpeciesResolver):
        self.db_path = db_path
        self.resolver = species_resolver

    def fetch_5day_weather_forecast(self, lat: float, lon: float) -> Optional[List[Dict[str, Any]]]:
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

    def fetch_72h_weather_forecast(self, lat: float, lon: float) -> Optional[List[Dict[str, Any]]]:
        return self.fetch_5day_weather_forecast(lat, lon)

    def generate_5day_timeline_prognosis(
        self,
        lat: float,
        lon: float,
        site_ids: List[str],
        start_dt: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Genereert een 5-daagse prognose waarin ELKE dag is opgesplitst in 2-uurlijkse blokken
        tussen zonsopgang en zonsondergang.
        """
        if start_dt is None:
            start_dt = datetime.now(timezone.utc)

        current_month = start_dt.month
        is_autumn = 7 <= current_month <= 11

        hourly_weather = self.fetch_5day_weather_forecast(lat, lon)
        corridor_data = CorridorEngine.fetch_corridor_forecasts(is_autumn=is_autumn)

        if not hourly_weather:
            return []

        all_days_results = []

        for day_offset in range(5):
            current_day_dt = start_dt + timedelta(days=day_offset)
            target_date_str = current_day_dt.strftime("%Y-%m-%d")
            day_weather = [h for h in hourly_weather if h["time"].startswith(target_date_str)]

            if not day_weather:
                continue

            sr_h, ss_h, sr_str, ss_str = calculate_sun_times(lat, lon, current_day_dt)

            day_of_year = current_day_dt.timetuple().tm_yday
            window_size = BsiConfig.BOI_FLOATING_WINDOW_DAYS
            day_start = day_of_year - (window_size // 2)
            day_end = day_of_year + (window_size // 2)

            species_profiles = self._fetch_phenology_profiles_from_db(day_start, day_end, site_ids)
            reg_boost = CorridorEngine.calculate_corridor_boost_at_time(current_day_dt, corridor_data, is_autumn=is_autumn)

            blocks = []
            for start_hour in range(sr_h, ss_h, 2):
                end_hour = min(ss_h, start_hour + 2)
                block_label = f"{start_hour:02d}:00 - {end_hour:02d}:00"

                matching_weather = [
                    h for h in day_weather
                    if start_hour <= datetime.fromisoformat(h["time"].replace("Z", "+00:00")).hour < end_hour
                ]
                w_sample = matching_weather[0] if matching_weather else day_weather[0]
                dt_block = current_day_dt.replace(hour=start_hour, minute=0, second=0)

                w_ctx = WeatherContext(
                    lat=lat,
                    lon=lon,
                    temp=w_sample.get("temp"),
                    wind_speed=w_sample.get("wind_speed"),
                    wind_deg=w_sample.get("wind_deg"),
                    cloud_percent=w_sample.get("cloud_cover"),
                    pressure=w_sample.get("pressure"),
                    visibility=10000,
                    pressure_trend=0.0
                )

                suggesties = AiInferenceEngine.calculate_bsi_prognosis(
                    lat=lat, lon=lon, dt=dt_block, weather=w_ctx,
                    species_profiles=species_profiles, neural_engine=None
                )

                combined_list = []
                for s_obj in suggesties:
                    s_obj.latin_name = self.resolver.get_latin(s_obj.soortid)
                    s_obj.score *= (1.0 + reg_boost)
                    s_obj.kans = int(min(98, s_obj.kans * (1.0 + (reg_boost * 0.5))))
                    combined_list.append(s_obj)

                top_species = sorted(combined_list, key=lambda x: (x.kans, x.score), reverse=True)[:8]

                bft = WeatherManagerUtils.ms_to_beaufort(w_sample.get("wind_speed", 0.0))
                wind_lbl = WeatherManagerUtils.deg_to_16_wind_label(w_sample.get("wind_deg"))
                temp_c = round(w_sample.get("temp", 0.0), 1)

                blocks.append({
                    "time_block": block_label,
                    "temp": temp_c,
                    "wind_bft": bft,
                    "wind_label": wind_lbl,
                    "wind_deg": float(w_sample.get("wind_deg", 0.0)),
                    "cloud_cover": w_sample.get("cloud_cover", 50.0),
                    "top_species": top_species
                })

            all_days_results.append({
                "date_str": target_date_str,
                "display_date": current_day_dt.strftime("%A %d %B").capitalize(),
                "sunrise": sr_str,
                "sunset": ss_str,
                "corridor_boost": reg_boost,
                "blocks": blocks
            })

        return all_days_results

    def generate_daily_timeline_prognosis(
            self,
            lat: float,
            lon: float,
            site_ids: List[str],
            target_dt: datetime
    ) -> List[Dict[str, Any]]:
        hourly_weather = self.fetch_72h_weather_forecast(lat, lon)
        if not hourly_weather:
            return []

        target_date_str = target_dt.strftime("%Y-%m-%d")
        day_weather = [h for h in hourly_weather if h["time"].startswith(target_date_str)]
        if not day_weather:
            day_weather = hourly_weather[:24]

        sr_h, ss_h, sr_str, ss_str = calculate_sun_times(lat, lon, target_dt)

        timeline_results = []

        day_of_year = target_dt.timetuple().tm_yday
        window_size = BsiConfig.BOI_FLOATING_WINDOW_DAYS
        day_start = day_of_year - (window_size // 2)
        day_end = day_of_year + (window_size // 2)
        species_profiles = self._fetch_phenology_profiles_from_db(day_start, day_end, site_ids)

        if not species_profiles:
            return []

        for start_hour in range(sr_h, ss_h, 2):
            end_hour = min(ss_h, start_hour + 2)
            block_label = f"{start_hour:02d}:00 - {end_hour:02d}:00"

            matching_weather = [
                h for h in day_weather
                if start_hour <= datetime.fromisoformat(h["time"].replace("Z", "+00:00")).hour < end_hour
            ]
            w_sample = matching_weather[0] if matching_weather else day_weather[0]
            dt_block = target_dt.replace(hour=start_hour, minute=0, second=0)

            w_ctx = WeatherContext(
                lat=lat,
                lon=lon,
                temp=w_sample.get("temp"),
                wind_speed=w_sample.get("wind_speed"),
                wind_deg=w_sample.get("wind_deg"),
                cloud_percent=w_sample.get("cloud_cover"),
                pressure=w_sample.get("pressure"),
                visibility=10000,
                pressure_trend=0.0
            )

            suggesties = AiInferenceEngine.calculate_bsi_prognosis(
                lat=lat, lon=lon, dt=dt_block, weather=w_ctx,
                species_profiles=species_profiles, neural_engine=None
            )

            bft = WeatherManagerUtils.ms_to_beaufort(w_sample.get("wind_speed", 0.0))
            wind_lbl = WeatherManagerUtils.deg_to_16_wind_label(w_sample.get("wind_deg"))
            temp_c = round(w_sample.get("temp", 0.0), 1)

            timeline_results.append({
                "time_block": block_label,
                "temp": temp_c,
                "wind_bft": bft,
                "wind_label": wind_lbl,
                "wind_deg": float(w_sample.get("wind_deg", 0.0)),
                "cloud_cover": w_sample.get("cloud_cover", 50.0),
                "sunrise": sr_str,
                "sunset": ss_str,
                "weather_summary": f"Wind: {wind_lbl} {bft}Bft | Temp: {temp_c}°C",
                "top_species": suggesties[:8]
            })

        return timeline_results

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