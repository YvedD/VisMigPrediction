import base64
import os
import sqlite3
import pandas as pd
from datetime import datetime
from config_loader import load_species


def get_db_path():
    return os.path.join("database", "voicetally.db")


def check_database():
    path = get_db_path()
    return os.path.exists(path), path

def fetch_species_weekly_distribution(soort_id, site_ids):
    """Haalt wekelijkse waarnemingen (0-53) op uit SQLite voor een soort[cite: 7]."""
    path = get_db_path()
    if not os.path.exists(path):
        return []
    try:
        conn = sqlite3.connect(path)
        placeholders = ','.join(['?'] * len(site_ids)) if site_ids else "''"
        query = f"""
            SELECT 
                CAST(strftime('%W', datetime(CAST(h.begintijd AS INTEGER), 'unixepoch')) AS INTEGER) as week,
                SUM(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER)) as count
            FROM waarnemingen w
            INNER JOIN telling_headers h ON w.tellingid = h.tellingid
            WHERE w.soortid = ? AND (h.telpostid IN ({placeholders}) OR ? = '')
            GROUP BY week
        """
        params = [str(soort_id)] + site_ids + [str(site_ids)]
        df = pd.read_sql(query, conn, params=params)
        conn.close()
        return df.to_dict(orient="records")
    except Exception as e:
        print(f"Fout bij ophalen weekdistributie: {e}")
        return []

def fetch_storm_wind_correlations(db_path: str, site_ids: list) -> pd.DataFrame:
    """
    Haalt historische windkracht vs. windrichting correlaties op voor de cluster,
    specifiek gericht op harde wind / stormscenario's (>= 5 Bft) voor kust- en pelagische soorten.
    """
    import sqlite3
    import pandas as pd

    query = """
        SELECT 
            w.soortid,
            UPPER(TRIM(h.windrichting)) as wind_richting,
            CAST(h.windkracht AS INTEGER) as wind_bft,
            COUNT(DISTINCT h.tellingid) as aantal_teldagen,
            SUM(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER) + CAST(w.aantal_plus AS INTEGER) + CAST(w.aantalterug_plus AS INTEGER)) as totaal_aantal,
            ROUND(AVG(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER)), 2) as gemiddeld_per_telling,
            MAX(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER)) as piek_aantal_eenmalig
        FROM waarnemingen w
        INNER JOIN telling_headers h ON w.tellingid = h.tellingid
        WHERE h.windkracht IS NOT NULL AND h.windkracht != '' 
          AND h.windrichting IS NOT NULL AND h.windrichting != ''
          AND CAST(h.windkracht AS INTEGER) >= 5 
          AND (h.telpostid IN ({seq}))
        GROUP BY w.soortid, wind_richting, wind_bft
        HAVING totaal_aantal > 2
        ORDER BY wind_bft DESC, totaal_aantal DESC;
    """.format(seq=','.join(['?'] * len(site_ids)) if site_ids else "''")

    try:
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql_query(query, conn, params=site_ids)
            return df
    except Exception as e:
        print(f"[DbManager] Fout bij ophalen storm wind correlaties: {e}")
        return pd.DataFrame()

def fetch_species_image_base64(identifier):
    """Haalt de binaire afbeeldingsdata (BLOB) op uit de `species_images` tabel

    op basis van wetenschappelijke of Nederlandse naam.
    """
    path = get_db_path()
    if not os.path.exists(path) or not identifier:
        return None

    try:
        conn = sqlite3.connect(path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND"
            " name='species_images';"
        )
        if cursor.fetchone():
            cursor.execute(
                "SELECT thumbnailBlob FROM species_images WHERE LOWER(latinName) ="
                " LOWER(?) OR LOWER(latinName) LIKE LOWER(?) LIMIT 1;",
                (identifier, f"%{identifier}%"),
            )
            row = cursor.fetchone()
            if row and row[0] and isinstance(row[0], bytes):
                encoded = base64.b64encode(row[0]).decode("utf-8")
                conn.close()
                return f"data:image/png;base64,{encoded}"
        conn.close()
    except Exception as e:
        pass

    return None


def fetch_real_species_profiles(telpost_id=None, target_dt=None):
    """Haalt historische waarnemingen op uit SQLite en past het

    Floating 7/9-Day Fenologische Venster toe op basis van de datum (Sectie 15).
    """
    path = get_db_path()
    if not os.path.exists(path):
        return []

    if target_dt is None:
        target_dt = datetime.now()

    day_of_year = target_dt.timetuple().tm_yday
    window_size = 9  # 9-daags floating window voor seizoensfiltratie
    day_start = day_of_year - (window_size // 2)
    day_end = day_of_year + (window_size // 2)

    try:
        conn = sqlite3.connect(path)

        # Query met fenologische dag-filtering en jaarovergang afhandeling (Sectie 15.4)[cite: 4]
        query = """
                SELECT w.soortid, \
                       SUM(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER)) as count,
                UPPER(h.windrichting) as mainWind,
                AVG(CAST(NULLIF(h.temperatuur, '') AS FLOAT)) as avgTemp,
                AVG(CAST(strftime('%H', datetime(CAST(COALESCE(w.tijdstip, h.begintijd) AS INTEGER), 'unixepoch', 'localtime')) AS INTEGER)) as avgHour,
                CAST(SUM(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER)) AS FLOAT) / 7.0 as expectedIndex,
                0 as isRemarkable,
                50 as bestWindCount,
                45 as currentWindCount
                FROM waarnemingen w
                    INNER JOIN telling_headers h \
                ON w.tellingid = h.tellingid
                WHERE ((CAST (strftime('%j' \
                    , datetime(CAST (h.begintijd AS INTEGER) \
                    , 'unixepoch')) AS INTEGER) BETWEEN ? \
                  AND ?)
                   OR (CAST (strftime('%j' \
                    , datetime(CAST (h.begintijd AS INTEGER) \
                    , 'unixepoch')) AS INTEGER) + 365 BETWEEN ? \
                  AND ?)
                   OR (CAST (strftime('%j' \
                    , datetime(CAST (h.begintijd AS INTEGER) \
                    , 'unixepoch')) AS INTEGER) - 365 BETWEEN ? \
                  AND ?))
                  AND (? IS NULL \
                   OR h.telpostid = ?)
                GROUP BY w.soortid
                ORDER BY count DESC; \
                """
        params = [
            day_start,
            day_end,
            day_start,
            day_end,
            day_start,
            day_end,
            telpost_id,
            telpost_id,
        ]
        df = pd.read_sql(query, conn, params=params)

        # Fallback: als het venster voor deze telpost te leeg is, probeer ruimer te filteren
        if df.empty:
            query_fallback = """
                             SELECT w.soortid, \
                                    SUM(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER)) as count,
                    UPPER(h.windrichting) as mainWind,
                    10.0 as avgHour,
                    10.0 as expectedIndex,
                    0 as isRemarkable,
                    50 as bestWindCount,
                    45 as currentWindCount
                             FROM waarnemingen w
                                 INNER JOIN telling_headers h \
                             ON w.tellingid = h.tellingid
                             GROUP BY w.soortid
                             ORDER BY count DESC
                                 LIMIT 20; \
                             """
            df = pd.read_sql(query_fallback, conn)

        conn.close()

        if df.empty:
            return []

        # Laad soortnamen uit species.json
        species_data = load_species()
        species_map = {}
        if species_data:
            raw_list = (
                species_data.get("json", [])
                if isinstance(species_data, dict)
                else species_data
            )
            for item in raw_list:
                if isinstance(item, dict):
                    sid = str(item.get("soortid", ""))
                    sname = item.get("soortnaam", f"Soort {sid}")
                    slatin = item.get("latin", "")
                    species_map[sid] = {"naam": sname, "latin": slatin}

        profiles = []
        for _, row in df.iterrows():
            sid = str(row["soortid"])
            info = species_map.get(sid, {"naam": f"Soort {sid}", "latin": ""})

            profiles.append({
                "soortid": sid,
                "soortnaam": info["naam"],
                "latin": info["latin"],
                "count": max(1, row["count"]),
                "mainWind": row["mainWind"] if row["mainWind"] else "NO",
                "avgHour": row["avgHour"] if pd.notnull(row["avgHour"]) else 10.0,
                "expectedIndex": row["expectedIndex"]
                if pd.notnull(row["expectedIndex"])
                else 1.0,
                "isRemarkable": row["isRemarkable"],
                "bestWindCount": row["bestWindCount"],
                "currentWindCount": row["currentWindCount"],
            })
        return profiles
    except Exception as e:
        print(f"Fout bij ophalen echte fenologische profielen: {e}")

    return []


def init_weather_archive_table():
    path = get_db_path()
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS weather_archive
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       telpostid
                       TEXT,
                       year
                       INTEGER,
                       time
                       INTEGER,
                       temperature
                       REAL,
                       wind_speed
                       REAL,
                       wind_direction
                       REAL,
                       pressure
                       REAL,
                       precipitation
                       REAL,
                       cloud_cover
                       REAL,
                       wind_bft
                       INTEGER,
                       wind_sector
                       TEXT,
                       pressure_trend
                       REAL,
                       UNIQUE
                   (
                       telpostid,
                       time
                   )
                       )
                   """)
    conn.commit()
    conn.close()


def save_weather_to_archive_safe(telpost_id, year, df_weather):
    if df_weather.empty:
        return
    path = get_db_path()
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    df_weather = df_weather.where(pd.notnull(df_weather), None)
    records = []
    for _, row in df_weather.iterrows():
        records.append((
            str(telpost_id),
            int(year),
            int(row.get("time_epoch", 0)) if row.get("time_epoch") else 0,
            float(row.get("temperature_2m"))
            if row.get("temperature_2m") is not None
            else None,
            float(row.get("wind_speed_10m"))
            if row.get("wind_speed_10m") is not None
            else None,
            float(row.get("wind_direction_10m"))
            if row.get("wind_direction_10m") is not None
            else None,
            float(row.get("surface_pressure"))
            if row.get("surface_pressure") is not None
            else None,
            float(row.get("precipitation"))
            if row.get("precipitation") is not None
            else None,
            float(row.get("cloud_cover"))
            if row.get("cloud_cover") is not None
            else None,
            int(row.get("wind_bft", 0))
            if row.get("wind_bft") is not None
            else 0,
            str(row.get("wind_sector", "Onbekend")),
            float(row.get("pressure_trend_6h", 0.0))
            if row.get("pressure_trend_6h") is not None
            else 0.0,
        ))
    cursor.executemany(
        """
        INSERT
        OR IGNORE INTO weather_archive (
            telpostid, year, time, temperature, wind_speed, wind_direction,
            pressure, precipitation, cloud_cover, wind_bft, wind_sector, pressure_trend
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
    conn.commit()
    conn.close()


def check_weather_archive_exists(telpost_id, year):
    path = get_db_path()
    if not os.path.exists(path):
        return False
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM weather_archive WHERE telpostid = ? AND year ="
        " ?;",
        (str(telpost_id), int(year)),
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count > 7000


def fetch_training_data(limit=10):
    path = get_db_path()
    conn = sqlite3.connect(path)
    query = """
            SELECT w.soortid, \
                   h.begintijd as sessionStart, \
                   w.tijdstip  as observationTime, \
                   h.windrichting, \
                   h.windkracht, \
                   h.temperatuur, \
                   h.bewolking, \
                   h.hpa, \
                   h.neerslag, \
                   h.telpostid
            FROM waarnemingen w
                     INNER JOIN telling_headers h ON w.tellingid = h.tellingid
            WHERE h.status = 'gearchiveerd' \
               OR h.status = 'geupload'
            ORDER BY h.begintijd DESC LIMIT ? \
            """
    df = pd.read_sql(query, conn, params=(limit,))
    conn.close()
    return df


def fetch_phenology_profile():
    path = get_db_path()
    conn = sqlite3.connect(path)
    query = """
            SELECT w.soortid, \
                   SUM(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER)) as totalCount, \
                   AVG(CAST(NULLIF(h.temperatuur, '') AS FLOAT))                   as avgTemp, \
                   UPPER(h.windrichting)                                           as mainWind, \
                   AVG(CAST(NULLIF(h.windkracht, '') AS FLOAT))                    as avgBft, \
                   AVG(CAST(NULLIF(h.hpa, '') AS FLOAT))                           as avgPressure
            FROM waarnemingen w
                     INNER JOIN telling_headers h ON w.tellingid = h.tellingid
            GROUP BY w.soortid
            ORDER BY totalCount DESC LIMIT 15 \
            """
    df = pd.read_sql(query, conn)
    conn.close()
    return df