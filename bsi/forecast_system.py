"""
bsi/forecast_system.py
Orchestratie van de 5-daagse (120-uurs) en dagelijkse BSI vogelprognoses
op basis van alle telposten in de database, een 7-daags venster en zonder limiet op het aantal soorten.
"""

import math
import requests
import streamlit as st
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from .config import BsiConfig
from .weather_service import WeatherContext, WeatherManagerUtils
from .inference_engine import AiInferenceEngine, VogelSuggestie
from .solar_engine import SolarTimeEngine
from .species_resolver import SpeciesResolver
from .corridor_engine import CorridorEngine
from .period_computer import periodize_hours


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


def wmo_code_to_precipitation_type(code) -> str:
    if code is None:
        return "Droog"
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "Droog"

    if code in {51, 53, 55, 56, 57}:
        return "Motregen"
    elif code in {61, 63, 65, 66, 67}:
        return "Regen"
    elif code in {71, 73, 75, 77}:
        return "Sneeuw"
    elif code in {80, 81, 82}:
        return "Buien"
    elif code in {85, 86}:
        return "Sneeuwbuien"
    elif code >= 95:
        return "Onweer"
    elif code in {1, 2, 3}:
        return "Bewolkt"
    else:
        return "Droog"


class BsiForecastSystem:
    def __init__(self, db_path: str, species_resolver: SpeciesResolver):
        self.db_path = db_path
        self.resolver = species_resolver
        BsiConfig.MIN_BSI_QUALITY_THRESHOLD = 15

    @staticmethod
    @st.cache_data(ttl=900)
    def fetch_5day_weather_forecast(lat: float, lon: float) -> Optional[Dict[str, Any]]:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,wind_speed_10m,wind_direction_10m,surface_pressure,cloud_cover,precipitation,precipitation_probability,weather_code"
            f"&daily=sunrise,sunset"
            f"&wind_speed_unit=ms&forecast_days=5&timezone=auto"
        )
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json()

            hourly = data.get("hourly", {})
            times = hourly.get("time", [])

            temps = hourly.get("temperature_2m", [])
            wind_speeds = hourly.get("wind_speed_10m", [])
            wind_degs = hourly.get("wind_direction_10m", [])
            pressures = hourly.get("surface_pressure", [])
            cloud_covers = hourly.get("cloud_cover", [])
            precips = hourly.get("precipitation", [])
            precip_probs = hourly.get("precipitation_probability", [])
            weather_codes = hourly.get("weather_code", [])

            hourly_result = []
            for i in range(len(times)):
                w_code = weather_codes[i] if i < len(weather_codes) else 0
                hourly_result.append({
                    "time": times[i],
                    "temp": temps[i] if i < len(temps) else 15.0,
                    "wind_speed": wind_speeds[i] if i < len(wind_speeds) else 3.0,
                    "wind_deg": wind_degs[i] if i < len(wind_degs) else 0.0,
                    "pressure": pressures[i] if i < len(pressures) else 1016.0,
                    "cloud_cover": cloud_covers[i] if i < len(cloud_covers) else 20.0,
                    "precip_mm": precips[i] if i < len(precips) else 0.0,
                    "precip_prob": precip_probs[i] if i < len(precip_probs) else 0,
                    "precip_type": wmo_code_to_precipitation_type(w_code)
                })

            daily = data.get("daily", {})
            daily_times = daily.get("time", [])
            sun_map = {}
            sun_times_raw = daily.get("sunrise", [])
            sunset_times_raw = daily.get("sunset", [])

            for j in range(len(daily_times)):
                date_key = daily_times[j]
                sr_dt_str = sun_times_raw[j] if j < len(sun_times_raw) else f"{date_key}T07:00"
                ss_dt_str = sunset_times_raw[j] if j < len(sunset_times_raw) else f"{date_key}T20:00"

                sr_time_part = sr_dt_str.split("T")[1][:5] if "T" in sr_dt_str else "07:00"
                ss_time_part = ss_dt_str.split("T")[1][:5] if "T" in ss_dt_str else "20:00"

                sr_parts = sr_time_part.split(":")
                ss_parts = ss_time_part.split(":")
                sr_float = int(sr_parts[0]) + int(sr_parts[1]) / 60.0
                ss_float = int(ss_parts[0]) + int(ss_parts[1]) / 60.0

                sun_map[date_key] = {
                    "sunrise_str": sr_time_part,
                    "sunset_str": ss_time_part,
                    "sunrise_float": sr_float,
                    "sunset_float": ss_float
                }

            return {
                "hourly": hourly_result,
                "sun_map": sun_map
            }
        except Exception as e:
            print(f"[ForecastSystem] Fout bij ophalen 5d forecast: {e}")
            return None

    def fetch_72h_weather_forecast(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        return self.fetch_5day_weather_forecast(lat, lon)

    def generate_5day_timeline_prognosis(
        self,
        lat: float,
        lon: float,
        site_ids: List[str],
        start_dt: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        if start_dt is None:
            start_dt = datetime.now(timezone.utc)

        current_month = start_dt.month
        is_autumn = 7 <= current_month <= 11

        forecast_data = self.fetch_5day_weather_forecast(lat, lon)
        corridor_data = CorridorEngine.fetch_corridor_forecasts(is_autumn=is_autumn)

        if not forecast_data:
            return []

        hourly_weather = forecast_data["hourly"]
        sun_map = forecast_data["sun_map"]
        all_days_results = []

        for day_offset in range(5):
            current_day_dt = start_dt + timedelta(days=day_offset)
            target_date_str = current_day_dt.strftime("%Y-%m-%d")
            day_weather = [h for h in hourly_weather if h["time"].startswith(target_date_str)]

            if not day_weather:
                continue

            sun_info = sun_map.get(target_date_str, {"sunrise_str": "07:07", "sunset_str": "20:20", "sunrise_float": 7.12, "sunset_float": 20.33})
            sr_float = sun_info["sunrise_float"]
            ss_float = sun_info["sunset_float"]
            sr_str = sun_info["sunrise_str"]
            ss_str = sun_info["sunset_str"]

            start_h = math.floor(sr_float)
            end_h = math.ceil(ss_float)

            day_of_year = current_day_dt.timetuple().tm_yday
            day_start = day_of_year - 3
            day_end = day_of_year + 3

            species_profiles = self._fetch_phenology_profiles_from_db(day_start, day_end)
            reg_boost = CorridorEngine.calculate_corridor_boost_at_time(current_day_dt, corridor_data, is_autumn=is_autumn)

            periods = periodize_hours(
                hourly_samples=day_weather,
                start_hour=start_h,
                end_hour=end_h
            )

            blocks = []
            for period in periods:
                p_start_h = period["start_hour"]
                p_end_h = period["end_hour"]
                wind_lbl = period["modal_wind_label"]
                bft = period["median_bft"]
                block_label = f"{period['start_time']} - {period['end_time']} ({wind_lbl} {bft}Bft)"

                matching_weather = [
                    h for h in day_weather
                    if p_start_h <= datetime.fromisoformat(h["time"].replace("Z", "+00:00")).hour < p_end_h
                ]
                w_sample = matching_weather[0] if matching_weather else day_weather[0]
                dt_block = current_day_dt.replace(hour=p_start_h, minute=0, second=0)

                pressures = [h.get("pressure", 1016.0) for h in matching_weather if h.get("pressure") is not None]
                avg_pressure = int(round(sum(pressures) / len(pressures))) if pressures else 1016

                w_ctx = WeatherContext(
                    lat=lat,
                    lon=lon,
                    temp=period["avg_temp"],
                    wind_speed=period["median_wind_speed"],
                    wind_deg=period["modal_wind_deg"],
                    cloud_percent=period["avg_cloud"],
                    pressure=float(avg_pressure),
                    visibility=10000,
                    pressure_trend=0.0
                )

                suggesties = AiInferenceEngine.calculate_bsi_prognosis(
                    lat=lat, lon=lon, dt=dt_block, weather=w_ctx,
                    species_profiles=species_profiles, neural_engine=None
                )

                combined_list = []
                for s_obj in suggesties:
                    if s_obj.expected_index <= 0.0:
                        continue
                    s_obj.latin_name = self.resolver.get_latin(s_obj.soortid)
                    s_obj.score *= (1.0 + reg_boost)
                    s_obj.kans = int(min(98, s_obj.kans * (1.0 + (reg_boost * 0.5))))
                    combined_list.append(s_obj)

                top_species = sorted(combined_list, key=lambda x: (x.kans, x.score), reverse=True)

                temp_c = round(period["avg_temp"], 1) if period["avg_temp"] is not None else 15.0

                blocks.append({
                    "time_block": block_label,
                    "temp": temp_c,
                    "wind_bft": bft,
                    "wind_label": wind_lbl,
                    "wind_deg": float(period["modal_wind_deg"]),
                    "pressure": avg_pressure,
                    "precip_mm": period["avg_precip_mm"],
                    "precip_prob": period["avg_precip_prob"],
                    "precip_type": w_sample.get("precip_type", "Droog"),
                    "cloud_cover": period["avg_cloud"] if period["avg_cloud"] is not None else 50.0,
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
        forecast_data = self.fetch_72h_weather_forecast(lat, lon)
        if not forecast_data:
            return []

        hourly_weather = forecast_data["hourly"]
        sun_map = forecast_data["sun_map"]

        target_date_str = target_dt.strftime("%Y-%m-%d")
        day_weather = [h for h in hourly_weather if h["time"].startswith(target_date_str)]
        if not day_weather:
            day_weather = hourly_weather[:24]

        sun_info = sun_map.get(target_date_str, {"sunrise_str": "07:07", "sunset_str": "20:20", "sunrise_float": 7.12, "sunset_float": 20.33})
        sr_float = sun_info["sunrise_float"]
        ss_float = sun_info["sunset_float"]
        sr_str = sun_info["sunrise_str"]
        ss_str = sun_info["sunset_str"]

        start_h = math.floor(sr_float)
        end_h = math.ceil(ss_float)

        timeline_results = []

        day_of_year = target_dt.timetuple().tm_yday
        day_start = day_of_year - 3
        day_end = day_of_year + 3
        species_profiles = self._fetch_phenology_profiles_from_db(day_start, day_end)

        if not species_profiles:
            return []

        periods = periodize_hours(
            hourly_samples=day_weather,
            start_hour=start_h,
            end_hour=end_h
        )

        for period in periods:
            p_start_h = period["start_hour"]
            p_end_h = period["end_hour"]
            wind_lbl = period["modal_wind_label"]
            bft = period["median_bft"]
            block_label = f"{period['start_time']} - {period['end_time']} ({wind_lbl} {bft}Bft)"

            matching_weather = [
                h for h in day_weather
                if p_start_h <= datetime.fromisoformat(h["time"].replace("Z", "+00:00")).hour < p_end_h
            ]
            w_sample = matching_weather[0] if matching_weather else day_weather[0]
            dt_block = target_dt.replace(hour=p_start_h, minute=0, second=0)

            pressures = [h.get("pressure", 1016.0) for h in matching_weather if h.get("pressure") is not None]
            avg_pressure = int(round(sum(pressures) / len(pressures))) if pressures else 1016

            w_ctx = WeatherContext(
                lat=lat,
                lon=lon,
                temp=period["avg_temp"],
                wind_speed=period["median_wind_speed"],
                wind_deg=period["modal_wind_deg"],
                cloud_percent=period["avg_cloud"],
                pressure=float(avg_pressure),
                visibility=10000,
                pressure_trend=0.0
            )

            suggesties = AiInferenceEngine.calculate_bsi_prognosis(
                lat=lat, lon=lon, dt=dt_block, weather=w_ctx,
                species_profiles=species_profiles, neural_engine=None
            )

            filtered_suggesties = [
                s for s in suggesties
                if s.expected_index > 0.0
            ]
            top_species = sorted(filtered_suggesties, key=lambda x: (x.kans, x.score), reverse=True)

            temp_c = round(period["avg_temp"], 1) if period["avg_temp"] is not None else 15.0

            timeline_results.append({
                "time_block": block_label,
                "temp": temp_c,
                "wind_bft": bft,
                "wind_label": wind_lbl,
                "wind_deg": float(period["modal_wind_deg"]),
                "pressure": avg_pressure,
                "precip_mm": period["avg_precip_mm"],
                "precip_prob": period["avg_precip_prob"],
                "precip_type": w_sample.get("precip_type", "Droog"),
                "cloud_cover": period["avg_cloud"] if period["avg_cloud"] is not None else 50.0,
                "sunrise": sr_str,
                "sunset": ss_str,
                "weather_summary": f"Wind: {wind_lbl} {bft}Bft | Temp: {temp_c}°C",
                "top_species": top_species
            })

        return timeline_results

    def _fetch_phenology_profiles_from_db(self, day_start: int, day_end: int) -> List[Dict[str, Any]]:
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
               AND h.telpostid != '5177'
            GROUP BY w.soortid
            ORDER BY count DESC
            LIMIT 150
        """
        params = [day_start, day_end, day_start, day_end, day_start, day_end]

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