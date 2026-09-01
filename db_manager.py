import os
import sqlite3
import pandas as pd


def get_db_path():
  return os.path.join("database", "voicetally.db")


def check_database():
  path = get_db_path()
  return os.path.exists(path), path


def get_table_list(db_path):
  conn = sqlite3.connect(db_path)
  tables_df = pd.read_sql(
      "SELECT name FROM sqlite_master WHERE type='table';", conn
  )
  conn.close()
  return tables_df


def init_weather_archive_table():
  """Zorgt dat de weather_archive tabel bestaat met een unieke constraint

  op (telpostid, time) en integer epoch tijdstempels conform BSI-blauwdruk.
  """
  path = get_db_path()
  conn = sqlite3.connect(path)
  cursor = conn.cursor()

  cursor.execute(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='weather_archive';"
  )
  table_exists = cursor.fetchone()

  if table_exists:
    cursor.execute("PRAGMA table_info(weather_archive);")
    columns = {col[1]: col[2] for col in cursor.fetchall()}
    if "telpostid" not in columns or "time" not in columns:
      cursor.execute("DROP TABLE weather_archive;")

  cursor.execute("""
        CREATE TABLE IF NOT EXISTS weather_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telpostid TEXT,
            year INTEGER,
            time INTEGER,
            temperature REAL,
            wind_speed REAL,
            wind_direction REAL,
            pressure REAL,
            precipitation REAL,
            cloud_cover REAL,
            wind_bft INTEGER,
            wind_sector TEXT,
            pressure_trend REAL,
            UNIQUE(telpostid, time)
        )
    """)
  conn.commit()
  conn.close()


def save_weather_to_archive_safe(telpost_id, year, df_weather):
  """Slaat het weerarchief veilig op via INSERT OR IGNORE

  om duplicaten en constraint-fouten te voorkomen.
  """
  if df_weather.empty:
    return

  path = get_db_path()
  conn = sqlite3.connect(path)
  cursor = conn.cursor()

  # Vervang Pandas NaNs door None zodat SQLite ze als NULL behandelt
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
        INSERT OR IGNORE INTO weather_archive (
            telpostid, year, time, temperature, wind_speed, wind_direction,
            pressure, precipitation, cloud_cover, wind_bft, wind_sector, pressure_trend
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
      records,
  )

  conn.commit()
  conn.close()


def check_weather_archive_exists(telpost_id, year):
  """Controleert of het weerarchief lokaal aanwezig is (minimaal 7000 uur-records)."""
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
        SELECT 
            w.soortid,
            h.begintijd as sessionStart,
            w.tijdstip as observationTime,
            h.windrichting,
            h.windkracht,
            h.temperatuur,
            h.bewolking,
            h.hpa,
            h.neerslag,
            h.telpostid
        FROM waarnemingen w
        INNER JOIN telling_headers h ON w.tellingid = h.tellingid
        WHERE h.status = 'gearchiveerd' OR h.status = 'geupload'
        ORDER BY h.begintijd DESC
        LIMIT ?
    """
  df = pd.read_sql(query, conn, params=(limit,))
  conn.close()
  return df


def fetch_phenology_profile():
  path = get_db_path()
  conn = sqlite3.connect(path)
  query = """
        SELECT
            w.soortid,
            SUM(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER)) as totalCount,
            AVG(CAST(NULLIF(h.temperatuur, '') AS FLOAT)) as avgTemp,
            UPPER(h.windrichting) as mainWind,
            AVG(CAST(NULLIF(h.windkracht, '') AS FLOAT)) as avgBft,
            AVG(CAST(NULLIF(h.hpa, '') AS FLOAT)) as avgPressure
        FROM waarnemingen w
        INNER JOIN telling_headers h ON w.tellingid = h.tellingid
        GROUP BY w.soortid
        ORDER BY totalCount DESC
        LIMIT 15
    """
  df = pd.read_sql(query, conn)
  conn.close()
  return df