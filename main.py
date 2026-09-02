import os
import math
import json
import pandas as pd
import sqlite3
import streamlit as st
import pydeck as pdk
import folium
from streamlit_folium import st_folium
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from config_loader import (
    load_neural_engine,
    load_species,
    load_telpost_locations,
)
from db_manager import (
    check_database,
    fetch_training_data,
    fetch_species_weekly_distribution,
    get_db_path,
)
from parsers import handle_excel_upload

from bsi.config import BsiConfig
from bsi.inference_engine import AiInferenceEngine
from bsi.weather_service import WeatherContext, WeatherManagerUtils
from bsi.forecast_system import BsiForecastSystem
from bsi.sparkline_engine import SparklineEngine
from bsi.card_evaluator import CardEvaluator
from bsi.image_manager import SpeciesImageManager
from bsi.species_resolver import SpeciesResolver

# Pagina configuratie
st.set_page_config(page_title="VisMigPrediction Platform", layout="wide")

# CSS injectie voor professionele CardViews met Smooth Hover/Touch Overlay
st.markdown("""
    <style>
        .forecast-date-header { font-size: 12px !important; font-weight: bold; color: #fff; margin-bottom: 4px; text-align: center; }
        .weather-box { background-color: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 8px; min-height: 80px; display: flex; flex-direction: column; justify-content: center; margin-bottom: 10px; color: #e2e8f0; font-size: 11px; text-align: center; }

        .bsi-card { 
            background-color: #ffffff; 
            border-radius: 8px; 
            padding: 10px; 
            margin-top: 8px; 
            margin-bottom: 8px; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.08); 
            border-left: 6px solid #ccc; 
            position: relative; 
            overflow: hidden; 
        }
        .bsi-header { font-size: 10px; font-weight: bold; text-transform: uppercase; margin-bottom: 3px; color: #666; display: flex; justify-content: space-between; align-items: center; }
        .bsi-title-container { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
        .bsi-species-img { width: 48px; height: 48px; border-radius: 6px; object-fit: cover; border: 1px solid #ddd; background-color: #f0f2f6; flex-shrink: 0; }
        .bsi-species-placeholder { width: 48px; height: 48px; border-radius: 6px; display: flex; align-items: center; justify-content: center; background-color: #f0f2f6; font-size: 20px; border: 1px solid #ddd; flex-shrink: 0; }
        .bsi-title { font-size: 13px; font-weight: bold; color: #111; margin: 0; line-height: 1.1; }
        .bsi-sub { font-size: 10px; color: #555; font-style: italic; margin-bottom: 4px; }
        .bsi-metrics { display: flex; gap: 6px; background: #f8f9fa; padding: 5px; border-radius: 4px; margin-bottom: 4px; }
        .metric-box { flex: 1; text-align: center; }
        .metric-val { font-size: 12px; font-weight: bold; color: #2c3e50; }
        .metric-label { font-size: 7px; color: #7f8c8d; text-transform: uppercase; }
        .peak-badge { font-size: 9px; color: #444; background: #eef2f5; padding: 3px 4px; border-radius: 4px; margin-bottom: 4px; display: inline-block; width: 100%; text-align: center; }
        .sparkline-img { width: 100%; height: 65px; object-fit: contain; margin-top: 2px; }

        /* Hover / Touch Overlay voor Details */
        .bsi-card-overlay {
            position: absolute;
            top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(255, 255, 255, 0.97);
            backdrop-filter: blur(2px);
            display: flex;
            flex-direction: column;
            justify-content: center;
            padding: 12px;
            opacity: 0;
            transition: opacity 0.25s ease-in-out;
            pointer-events: none;
            z-index: 10;
            box-sizing: border-box;
            border-radius: 8px;
        }
        .bsi-card:hover .bsi-card-overlay, .bsi-card:active .bsi-card-overlay {
            opacity: 1;
            pointer-events: auto;
        }
        .overlay-title { font-size: 13px; font-weight: bold; color: #1e293b; margin-bottom: 4px; }
        .overlay-text { font-size: 10px; color: #475569; margin-bottom: 6px; line-height: 1.3; }
    </style>
""", unsafe_allow_html=True)

st.title("🦅 VisMigPrediction - Platform")


# --- Hulpfunctie: Haversine Afstandsberekening ---
def calculate_distance_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return R * c


# --- Hulpfunctie: Inlezen van sites.json voor echte telpostnamen ---
def load_sites_mapping():
    possible_paths = [
        Path("serverdata/sites.json"),
        Path("VT5/serverdata/sites.json"),
        Path("C:/Eigen bestanden Yves/Programeren/Python/VisMigPrediction/serverdata/sites.json")
    ]
    mapping = {}
    for p in possible_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                raw_list = data.get("json", data if isinstance(data, list) else [])
                for item in raw_list:
                    if isinstance(item, dict):
                        sid = str(item.get("telpostid", "")).strip()
                        sname = str(item.get("telpostnaam", "")).strip()
                        if sid and sname:
                            mapping[sid] = sname
                if mapping:
                    break
            except Exception as e:
                print(f"[SitesLoader] Fout bij laden {p}: {e}")
    return mapping


# --- Hulpfunctie: Haal alle telposten op met coördinaten en namen ---
def get_available_telpost_options():
    telpost_locations = load_telpost_locations()
    sites_mapping = load_sites_mapping()

    raw_list = []
    if isinstance(telpost_locations, dict):
        raw_list = telpost_locations.get("locaties", telpost_locations.get("json", []))
    elif isinstance(telpost_locations, list):
        raw_list = telpost_locations

    posts = []
    for item in raw_list:
        sid = str(item.get("telpostid", "")).strip()
        lat = pd.to_numeric(item.get("latitude"), errors='coerce')
        lon = pd.to_numeric(item.get("longitude"), errors='coerce')
        if sid and not math.isnan(lat) and not math.isnan(lon):
            name = sites_mapping.get(sid, f"Telpost {sid}")
            posts.append({
                "telpostid": sid,
                "naam": name,
                "lat": lat,
                "lon": lon
            })
    return posts


# --- Hulpfunctie: Cluster-gebaseerde fenologie profielen ophalen (Alle data binnen 35km) ---
def fetch_cluster_species_profiles(db_path: str, site_ids: List[str], target_dt: datetime) -> List[Dict[str, Any]]:
    """
    Haalt de historische waarnemingen op voor ALLE telposten in de 35km cluster
    binnen het 7/9-daagse floating fenologische venster.
    """
    day_of_year = target_dt.timetuple().tm_yday
    window_size = BsiConfig.BOI_FLOATING_WINDOW_DAYS
    day_start = day_of_year - (window_size // 2)
    day_end = day_of_year + (window_size // 2)

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
        LIMIT 120
    """.format(seq=','.join(['?'] * len(site_ids)) if site_ids else "''")

    params = [day_start, day_end, day_start, day_end, day_start, day_end] + site_ids
    resolver = SpeciesResolver(Path("."))

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            rows = cursor.execute(query, params).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["soortnaam"] = resolver.get_name(d["soortid"])
                d["latin"] = resolver.get_latin(d["soortid"])
                d["expectedIndex"] = float(d["count"]) / max(1.0, float(len(site_ids)))
                results.append(d)
            return results
    except Exception as e:
        print(f"[ClusterProfiles] SQLite Fout: {e}")
        return []


# --- UITGEBREIDE UNIEKE GILDEN KLEURENPALET ---
GILDE_KLEUREN = {
    "Roofvogels (Zwevers)": "#d9534f",  # Rood
    "Roofvogels (Actief)": "#c0392b",  # Donkerrood
    "Zangvogels": "#f0ad4e",  # Oranje/Geel
    "Zeevogels (Pelagics)": "#0275d8",  # Diepblauw
    "Kustvogels (Zee-eenden/Duikers/Futen)": "#1abc9c",  # Turquoise
    "Watervogels (Ganzen/Grondeleenden)": "#3498db",  # Lichtblauw
    "Landvogels": "#5cb85c",  # Groen
    "Speciale Landvogels": "#27ae60",  # Donkergroen
    "Reigers": "#e67e22",  # Amber
    "Steltlopers": "#9b59b6",  # Paars
    "Meeuwen & Sterns": "#e84393",  # Roze / Magenta
    "Ooievaars (Zwevers)": "#d35400"  # Oranjebruin
}

# --- SIDEBAR: NAVIGATIE & PARAMETER TUNING ---
st.sidebar.title("Navigatie")
app_mode = st.sidebar.selectbox(
    "Kies een optie", ["Overzicht", "Excel Upload (.xlsx)", "Prognoses", "Cluster Kaart"]
)

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ BSI Motor Fijnafstelling")

custom_min_threshold = st.sidebar.slider(
    "Minimale Kwaliteitsdrempel (%)",
    min_value=5, max_value=60, value=int(BsiConfig.MIN_BSI_QUALITY_THRESHOLD), step=5
)
custom_wind_tolerance = st.sidebar.slider(
    "Wind-DNA Tolerantie (graden)",
    min_value=2.0, max_value=30.0, value=float(BsiConfig.WIND_TOLERANCE_DEGREES), step=0.5
)
custom_is_coastal = st.sidebar.checkbox(
    "Kust-status (Is Coastal Site)",
    value=bool(BsiConfig.IS_COASTAL_SITE)
)
custom_coastal_penalty = st.sidebar.slider(
    "Kust Veto / Aanlandige Wind Straf",
    min_value=0.05, max_value=1.0, value=float(BsiConfig.COASTAL_ONSHORE_PENALTY), step=0.05
)

BsiConfig.MIN_BSI_QUALITY_THRESHOLD = custom_min_threshold
BsiConfig.WIND_TOLERANCE_DEGREES = custom_wind_tolerance
BsiConfig.IS_COASTAL_SITE = custom_is_coastal
BsiConfig.COASTAL_ONSHORE_PENALTY = custom_coastal_penalty

# --- PAGINA 1: OVERZICHT ---
if app_mode == "Overzicht":
    st.header("📋 Systeemstatus & Data-integratie")
    db_status, db_path = check_database()
    if not db_status:
        st.error(f"❌ Kan SQLite database niet vinden op: {db_path}")
    else:
        st.success("✅ Lokale SQLite Room-database is gekoppeld.")

# --- PAGINA 2: EXCEL UPLOAD ---
elif app_mode == "Excel Upload (.xlsx)":
    st.header("📤 Upload Teldata van Telpost")
    uploaded_files = st.file_uploader("Sleep je .xlsx bestanden hierheen", type=["xlsx", "xls"],
                                      accept_multiple_files=True)
    if uploaded_files:
        handle_excel_upload(uploaded_files)

# --- PAGINA 3: PROGNOSES ---
elif app_mode == "Prognoses":
    st.header("📈 BSI 4.1 Migratie Prognoses & Toekomstvenster")
    mode_choice = st.radio("Selecteer Modus", ["Live Prognose (Enkele Datum)", "+5 Dagen (120-Uur) Naast Elkaar"],
                           horizontal=True)

    all_telposts = get_available_telpost_options()
    formatted_telpost_options = [f"{p['telpostid']} - {p['naam']}" for p in all_telposts] if all_telposts else [
        "4310 - Spanjaardduinen"]

    col_p1, col_p2 = st.columns(2)
    with col_p1:
        selected_telpost_str = st.selectbox(
            "Selecteer Hoofdtelpost",
            formatted_telpost_options,
        )
    with col_p2:
        if mode_choice.startswith("Live"):
            prognose_datum = st.date_input("Datum voor prognose", value=datetime.now())

    selected_telpost_id = selected_telpost_str.split(" - ")[0]

    main_lat, main_lon = 52.05, 4.25
    cluster_site_ids = [selected_telpost_id]

    if all_telposts:
        main_post_obj = next((p for p in all_telposts if str(p['telpostid']) == str(selected_telpost_id)), None)
        if main_post_obj:
            main_lat, main_lon = main_post_obj['lat'], main_post_obj['lon']
            cluster_site_ids = []
            for p in all_telposts:
                dist = calculate_distance_km(main_lat, main_lon, p['lat'], p['lon'])
                if dist <= 35.0:
                    cluster_site_ids.append(str(p['telpostid']))

    resolver = SpeciesResolver(Path("."))
    db_path_str = get_db_path()
    evaluator = CardEvaluator(db_path_str, resolver)
    image_manager = SpeciesImageManager(db_path_str)

    if mode_choice.startswith("Live"):
        if st.button("🔮 Genereer Live BSI Prognose (35km Cluster Pooling)"):
            st.success(
                f"✅ BSI Engine gestart voor telpost **{selected_telpost_str}** met **{len(cluster_site_ids)} telpost(en)** in de 35km cluster!")

            with st.spinner("Multi-site data pooling toepassen en BSI-inferentie uitvoeren..."):
                path = get_db_path()

                weather = None
                if os.path.exists(path):
                    conn = sqlite3.connect(path)
                    query = "SELECT temperature, wind_speed, wind_direction, pressure, cloud_cover FROM weather_archive WHERE telpostid = ? ORDER BY time DESC LIMIT 1;"
                    df_w = pd.read_sql(query, conn, params=(selected_telpost_id,))
                    conn.close()
                    if not df_w.empty:
                        r = df_w.iloc[0]
                        weather = WeatherContext(lat=main_lat, lon=main_lon, temp=r["temperature"],
                                                 wind_speed=r["wind_speed"],
                                                 wind_deg=r["wind_direction"], cloud_percent=r["cloud_cover"],
                                                 pressure=r["pressure"], visibility=10000, pressure_trend=1.5)

                if not weather:
                    weather = WeatherContext(lat=main_lat, lon=main_lon, temp=15.0, wind_speed=5.0, wind_deg=45.0,
                                             cloud_percent=4.0, pressure=1016.0, visibility=10000, pressure_trend=1.0)

                dt_target = datetime.combine(prognose_datum, datetime.now().time())
                species_profiles = fetch_cluster_species_profiles(db_path_str, cluster_site_ids, dt_target)

                if not species_profiles:
                    st.warning("⚠️ Geen waarnemingen gevonden binnen dit fenologische venster voor deze cluster.")
                else:
                    suggesties = AiInferenceEngine.calculate_bsi_prognosis(lat=main_lat, lon=main_lon, dt=dt_target,
                                                                           weather=weather,
                                                                           species_profiles=species_profiles)

                    if not suggesties:
                        st.warning("⚠️ Geen enkele soort voldeed aan de kwaliteitsdrempel.")
                    else:
                        st.success(
                            f"🎯 {len(suggesties)} vogelsoorten succesvol doorgerekend op basis van de 35km cluster!")

                        for i, item in enumerate(suggesties[:10]):
                            card_data = evaluator.build_comparative_card(item, item, cluster_site_ids)
                            if not card_data:
                                continue

                            bc = GILDE_KLEUREN.get(card_data.guild_name, "#5cb85c")
                            img_data_uri = image_manager.get_species_image_base64(card_data.latin_name)
                            img_html = f'<img src="{img_data_uri}" class="bsi-species-img" alt="{card_data.latin_name}">' if img_data_uri else '<div class="bsi-species-placeholder">🦅</div>'

                            weekly_rows = fetch_species_weekly_distribution(card_data.soortid, cluster_site_ids)
                            norm_buf = SparklineEngine.prepare_normalized_buffer(weekly_rows)
                            spark_uri = SparklineEngine.get_sparkline_base64(norm_buf, target_dt=dt_target)
                            spark_html = f'<img src="{spark_uri}" class="sparkline-img" alt="Fenologie">'

                            large_spark_uri = SparklineEngine.get_sparkline_base64(norm_buf, target_dt=dt_target,
                                                                                   width_px=320, height_px=90)
                            large_spark_html = f'<img src="{large_spark_uri}" style="width:100%; border-radius:4px; margin-top:4px;" alt="Uitvergrote Fenologie">'

                            card_html = (
                                f'<div class="bsi-card" style="border-left-color: {bc};">'
                                f'<div class="bsi-card-overlay">'
                                f'<div class="overlay-title">🔍 {card_data.soortnaam}</div>'
                                f'<div class="overlay-text"><b>Gilde:</b> {card_data.guild_name}<br>'
                                f'<b>AI Model:</b> {card_data.sources_label} (Heur: {card_data.heuristic_prob}% | Proto: {card_data.prototype_prob}%)<br>'
                                f'<b>Norm Score (Cluster):</b> {card_data.norm_score_ex_h:.2f} ex/u<br>'
                                f'<b>Voorjaar Piek:</b> {card_data.spring_peak}<br>'
                                f'<b>Najaar Piek:</b> {card_data.autumn_peak}</div>'
                                f'{large_spark_html}'
                                f'</div>'
                                f'<div class="bsi-header" style="color: {bc};"><span>🛡️ {card_data.guild_name}</span><span>H:{card_data.heuristic_prob}% | P:{card_data.prototype_prob}%</span></div>'
                                f'<div class="bsi-title-container">{img_html}<div>'
                                f'<div class="bsi-title">{card_data.soortnaam} <span style="font-size: 11px; font-weight: normal; color: #666;">({card_data.latin_name})</span></div>'
                                f'<div class="bsi-sub" style="margin-bottom: 0;">{card_data.sources_label} (Cluster: {len(cluster_site_ids)} posten)</div>'
                                f'</div></div>'
                                f'<div class="bsi-metrics">'
                                f'<div class="metric-box"><div class="metric-val" style="color: #27ae60;">{card_data.display_prob}%</div><div class="metric-label">BSI Kans</div></div>'
                                f'<div class="metric-box"><div class="metric-val">{card_data.norm_score_ex_h:.2f} ex/u</div><div class="metric-label">Norm Score</div></div>'
                                f'</div>'
                                f'<div class="peak-badge">📅 <b>Voorjaar:</b> {card_data.spring_peak} | <b>Najaar:</b> {card_data.autumn_peak}</div>'
                                f'{spark_html}'
                                f'</div>'
                            )
                            st.markdown(card_html, unsafe_allow_html=True)

    else:  # +5 Dagen Naast Elkaar (5 Kolommen)
        if st.button("🚀 Genereer 120-Uur (+5 Dagen) Cluster Vergelijking"):
            with st.spinner(
                    "120-uurs weersvoorspelling, Europese corridors en 35km cluster multi-site data doorrekenen..."):
                forecast_sys = BsiForecastSystem(get_db_path(), resolver)
                forecast_results = forecast_sys.generate_5day_prognosis(main_lat, main_lon, site_ids=cluster_site_ids)

                if not forecast_results:
                    st.warning("⚠️ Kon geen 5-daagse prognose genereren.")
                else:
                    st.success(
                        f"✅ 120-Uurs Toekomstvenster voor cluster ({len(cluster_site_ids)} posten) succesvol geladen!")

                    day_cols = st.columns(len(forecast_results))

                    for idx, col in enumerate(day_cols):
                        res = forecast_results[idx]
                        with col:
                            st.markdown(f'<div class="forecast-date-header">📅 {res.display_date}</div>',
                                        unsafe_allow_html=True)
                            st.markdown(
                                f'<div class="weather-box">🌤️ {res.weather_summary}<br>🌍 <b>Corridor</b>: +{int(res.corridor_boost * 100)}%</div>',
                                unsafe_allow_html=True)

                            if not res.top_species:
                                st.write("Geen trek verwacht.")
                            else:
                                for s_idx, item in enumerate(res.top_species):
                                    card_data = evaluator.build_comparative_card(item, item, cluster_site_ids)
                                    if not card_data:
                                        continue

                                    bc = GILDE_KLEUREN.get(card_data.guild_name, "#5cb85c")
                                    img_data_uri = image_manager.get_species_image_base64(card_data.latin_name)
                                    img_html = f'<img src="{img_data_uri}" class="bsi-species-img" alt="{card_data.latin_name}">' if img_data_uri else '<div class="bsi-species-placeholder">🦅</div>'

                                    dt_item = datetime.strptime(res.date_str, "%Y-%m-%d")
                                    weekly_rows = fetch_species_weekly_distribution(card_data.soortid, cluster_site_ids)
                                    norm_buf = SparklineEngine.prepare_normalized_buffer(weekly_rows)
                                    spark_uri = SparklineEngine.get_sparkline_base64(norm_buf, target_dt=dt_item)
                                    spark_html = f'<img src="{spark_uri}" class="sparkline-img" alt="Fenologie">'

                                    large_spark_uri = SparklineEngine.get_sparkline_base64(norm_buf, target_dt=dt_item,
                                                                                           width_px=320, height_px=90)
                                    large_spark_html = f'<img src="{large_spark_uri}" style="width:100%; border-radius:4px; margin-top:4px;" alt="Uitvergrote Fenologie">'

                                    card_html = (
                                        f'<div class="bsi-card" style="border-left-color: {bc};">'
                                        f'<div class="bsi-card-overlay">'
                                        f'<div class="overlay-title">🔍 {card_data.soortnaam}</div>'
                                        f'<div class="overlay-text"><b>Gilde:</b> {card_data.guild_name}<br>'
                                        f'<b>AI Model:</b> {card_data.sources_label} (Heur: {card_data.heuristic_prob}% | Proto: {card_data.prototype_prob}%)<br>'
                                        f'<b>Norm Score (Cluster):</b> {card_data.norm_score_ex_h:.2f} ex/u<br>'
                                        f'<b>Voorjaar Piek:</b> {card_data.spring_peak}<br>'
                                        f'<b>Najaar Piek:</b> {card_data.autumn_peak}</div>'
                                        f'{large_spark_html}'
                                        f'</div>'
                                        f'<div class="bsi-header" style="color: {bc};"><span>{card_data.guild_name}</span><span>H:{card_data.heuristic_prob}% | P:{card_data.prototype_prob}%</span></div>'
                                        f'<div class="bsi-title-container">{img_html}<div>'
                                        f'<div class="bsi-title">{card_data.soortnaam}</div>'
                                        f'<div style="font-size: 9px; color: #666; font-style: italic;">{card_data.latin_name}</div>'
                                        f'</div></div>'
                                        f'<div class="bsi-metrics">'
                                        f'<div class="metric-box"><div class="metric-val" style="color: #27ae60;">{card_data.display_prob}%</div><div class="metric-label">Kans</div></div>'
                                        f'<div class="metric-box"><div class="metric-val">{card_data.norm_score_ex_h:.1f}</div><div class="metric-label">Norm/u</div></div>'
                                        f'</div>'
                                        f'<div class="peak-badge" style="font-size:9px; padding:2px;"><b>Voorjaar:</b> {card_data.spring_peak} | <b>Najaar:</b> {card_data.autumn_peak}</div>'
                                        f'{spark_html}'
                                        f'</div>'
                                    )
                                    st.markdown(card_html, unsafe_allow_html=True)

# --- PAGINA 4: CLUSTER KAART ---
elif app_mode == "Cluster Kaart":
    st.header("🗺️ Telposten & 35km Cluster Visualisatie (OpenStreetMap)")
    st.write(
        "Selecteer hieronder een hoofdtelpost. De kaart toont de 35 km cluster-omtrek, met **rode** markers voor de hoofdpost, **groene** markers voor telposten binnen de cluster, en **blauwe** markers voor posten daarbuiten.")

    telpost_locations = load_telpost_locations()
    sites_mapping = load_sites_mapping()

    if not telpost_locations:
        st.warning("⚠️ Kon telpost_locaties.json niet laden.")
    else:
        raw_list = telpost_locations.get("locaties", []) if isinstance(telpost_locations, dict) else telpost_locations
        posts_df = pd.DataFrame(raw_list)

        if posts_df.empty:
            st.warning("⚠️ Geen locaties gevonden in telpost_locaties.json.")
        else:
            posts_df['lat'] = pd.to_numeric(posts_df.get('latitude'), errors='coerce')
            posts_df['lon'] = pd.to_numeric(posts_df.get('longitude'), errors='coerce')
            posts_df['telpostid'] = posts_df.get('telpostid', '').astype(str)

            posts_df['naam'] = posts_df['telpostid'].map(sites_mapping).fillna("Telpost " + posts_df['telpostid'])

            posts_df = posts_df.dropna(subset=['lat', 'lon'])

            main_post_name = st.selectbox("Selecteer Hoofdtelpost (Cluster Centrum)", posts_df['naam'].tolist(),
                                          index=0)
            main_row = posts_df[posts_df['naam'] == main_post_name].iloc[0]
            main_lat, main_lon = main_row['lat'], main_row['lon']

            m = folium.Map(location=[main_lat, main_lon], zoom_start=10, control_scale=True)

            folium.TileLayer('openstreetmap', name='Standaard (OSM)').add_to(m)
            folium.TileLayer(
                tiles='https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
                attr='Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                name='Topografisch (OpenTopoMap)'
            ).add_to(m)
            folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                attr='Tiles &copy; Esri',
                name='Satelliet (Esri)'
            ).add_to(m)

            folium.Circle(
                location=[main_lat, main_lon],
                radius=35000,
                color='#2ecc71',
                weight=2,
                fill=True,
                fill_color='#2ecc71',
                fill_opacity=0.08,
                tooltip="35 km Cluster Straal"
            ).add_to(m)

            cluster_members = []
            for _, row in posts_df.iterrows():
                dist = calculate_distance_km(main_lat, main_lon, row['lat'], row['lon'])
                is_in_cluster = dist <= 35.0
                is_main = (row['naam'] == main_post_name)

                if is_main:
                    marker_color = 'red'
                    icon_name = 'star'
                elif is_in_cluster:
                    marker_color = 'green'
                    icon_name = 'ok-sign'
                else:
                    marker_color = 'blue'
                    icon_name = 'info-sign'

                folium.Marker(
                    location=[row['lat'], row['lon']],
                    popup=f"<b>{row['naam']}</b><br>ID: {row['telpostid']}<br>Afstand tot hoofdpost: {dist:.1f} km",
                    tooltip=row['naam'],
                    icon=folium.Icon(color=marker_color, icon=icon_name, prefix='glyphicon')
                ).add_to(m)

                cluster_members.append({
                    "telpostid": row["telpostid"],
                    "naam": row["naam"],
                    "afstand_km": round(dist, 1),
                    "in_cluster": is_in_cluster
                })

            folium.LayerControl().add_to(m)

            st_data = st_folium(m, width=1200, height=550)

            cluster_df = pd.DataFrame(cluster_members)
            in_cluster_count = len(cluster_df[cluster_df['in_cluster'] == True])
            st.info(f"📍 **{main_post_name}** heeft **{in_cluster_count} telpost(en)** binnen de 35 km straal.")

            st.subheader("📋 Overzicht Cluster Leden (< 35 km)")
            active_cluster = cluster_df[cluster_df['in_cluster'] == True][['telpostid', 'naam', 'afstand_km']]
            st.dataframe(active_cluster, use_container_width=True)