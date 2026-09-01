from datetime import date, datetime, timedelta
import json
import os
import time
import numpy as np
import pandas as pd
import requests
from db_manager import (
    check_weather_archive_exists,
    init_weather_archive_table,
    save_weather_to_archive_safe,
)


def load_telpost_coordinates(telpost_id):
  """Zoekt de coördinaten op uit telpost_locaties.json."""
  path = os.path.join("serverdata", "telpost_locaties.json")
  if os.path.exists(path):
    with open(path, "r", encoding="utf-8") as f:
      data = json.load(f)
      locaties = data.get("locaties", [])
      for loc in locaties:
        if str(loc.get("telpostid")) == str(telpost_id):
          return float(loc.get("latitude")), float(loc.get("longitude"))
  return None, None


def m_s_to_beaufort(wind_speed_ms):
  """Converteert windsnelheid in m/s naar Beaufort."""
  if pd.isna(wind_speed_ms):
    return 0
  limits = [
      0.3,
      1.6,
      3.4,
      5.5,
      8.0,
      10.8,
      13.9,
      17.2,
      20.8,
      24.5,
      28.4,
      32.6,
  ]
  for bft, limit in enumerate(limits):
    if wind_speed_ms < limit:
      return bft
  return 12


def degrees_to_wind_sector(degrees):
  """Converteert windrichting in graden naar 16 windsectoren."""
  if pd.isna(degrees):
    return "Onbekend"
  sectors = [
      "N",
      "NNO",
      "NO",
      "ONO",
      "O",
      "OZO",
      "ZO",
      "ZZO",
      "Z",
      "ZZW",
      "ZW",
      "WZW",
      "W",
      "WNW",
      "NW",
      "NNW",
  ]
  index = int((degrees + 11.25) / 22.5) % 16
  return sectors[index]


def ensure_weather_archived(telpost_id, year):
  """Haalt het weerarchief op via Open-Meteo met inachtneming van

  de 2-dagen regel, Unix Epoch conversie en veilige batch-opslag[cite: 3].
  """
  init_weather_archive_table()

  # 1. Check of het archief lokaal aanwezig is
  if check_weather_archive_exists(telpost_id, year):
    return True

  # 2. Coördinaten ophalen
  lat, lon = load_telpost_coordinates(telpost_id)
  if lat is None or lon is None:
    print(f"⚠️ Geen coördinaten gevonden voor telpost {telpost_id}")
    return False

  target_year = int(year)
  today = date.today()

  start_date_obj = date(target_year, 1, 1)
  target_end_date_obj = date(target_year, 12, 31)

  # De strikte 2-dagen regel van de Android BSI logica
  max_allowed_date = today - timedelta(days=2)

  if start_date_obj > max_allowed_date:
    print(
        f"⚠️ Jaar {target_year} ligt te dicht bij vandaag of in de toekomst;"
        " archief nog niet beschikbaar."
    )
    return False

  effective_end_date = min(target_end_date_obj, max_allowed_date)

  url = "https://archive-api.open-meteo.com/v1/archive"
  params = {
      "latitude": lat,
      "longitude": lon,
      "start_date": start_date_obj.strftime("%Y-%m-%d"),
      "end_date": effective_end_date.strftime("%Y-%m-%d"),
      "hourly": (
          "temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,wind_direction_10m,precipitation,cloud_cover"
      ),
      "windspeed_unit": "ms",
      "timezone": "UTC",
  }

  try:
    # 1.0 seconde pauze (throttling / dispatcher breathing)
    time.sleep(1.0)
    response = requests.get(url, params=params, timeout=30)

    if response.status_code == 200:
      data = response.json()
      hourly_data = data.get("hourly", {})
      df = pd.DataFrame.from_dict(hourly_data)

      if not df.empty:
        # Cruciaal: Omzetten naar Unix Epoch Seconds (integer) conform BSI engine[cite: 3]
        df["time_epoch"] = pd.to_datetime(df["time"]).astype(int) // 10**9

        df["wind_bft"] = df["wind_speed_10m"].apply(m_s_to_beaufort)
        df["wind_sector"] = df["wind_direction_10m"].apply(
            degrees_to_wind_sector
        )
        df["pressure_trend_6h"] = (
            df["surface_pressure"] - df["surface_pressure"].shift(6)
        ).fillna(0.0)

        # Veilige opslag met INSERT OR IGNORE
        save_weather_to_archive_safe(telpost_id, year, df)
        return True
    else:
      print(
          f"❌ Open-Meteo Fout bij telpost {telpost_id} ({year}):"
          f" {response.status_code} - {response.text}"
      )
  except Exception as e:
    print(
        f"❌ Netwerkfout bij downloaden weerarchief {year} voor telpost {telpost_id}: "
        f"{type(e).__name__} - {e}"
    )

  return False