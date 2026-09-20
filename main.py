import os
import math
import json
import base64
import pandas as pd
import sqlite3
import streamlit as st
import pydeck as pdk
import folium
from streamlit_folium import st_folium
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from PIL import Image
import subprocess
import threading
import time
import re

from app_paths import project_path
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
from bsi.neural_engine import LiteNeuralEngine
from bsi.expert_knowledge import ExpertKnowledgeBase
from bsi.weather_service import WeatherContext, WeatherManagerUtils, AiWeatherService
from bsi.forecast_system import BsiForecastSystem
from bsi.sparkline_engine import SparklineEngine
from bsi.card_evaluator import CardEvaluator
from bsi.image_manager import SpeciesImageManager
from bsi.species_resolver import SpeciesResolver
from site_dna_builder import generate_sites_dna

# Nieuwe module voor telpost registratie en beheer
import telpost_manager

# Veilige inlading van het BSI Logo als Favicon via PIL
icon_path = project_path("BSI_logo.png")
page_icon_img = Image.open(icon_path) if icon_path.exists() else "🦅"

# Pagina configuratie
st.set_page_config(
    page_title="VisMigPrediction Platform",
    page_icon=page_icon_img,
    layout="wide"
)

# Vaste drempel op 15%
BsiConfig.MIN_BSI_QUALITY_THRESHOLD = 15

# --- Optionele cloudflared tunnel voor lokaal testen ---
ENABLE_TUNNEL = os.getenv("VISMIG_ENABLE_TUNNEL", "0") == "1"
if 'cloudflared_proc' not in st.session_state:
    st.session_state.cloudflared_proc = None
if 'tunnel_url_cache' not in st.session_state:
    st.session_state.tunnel_url_cache = ""


def start_background_tunnel(port: int = 8501):
    """Start cloudflared automatisch in de achtergrond, print output naar de terminal en vang de URL op."""
    if not ENABLE_TUNNEL:
        return
    if st.session_state.cloudflared_proc is not None:
        return

    exe_name = "cloudflared.exe" if os.name == "nt" else "cloudflared"
    cloudflared_path = project_path(exe_name) if project_path(exe_name).exists() else "cloudflared"

    try:
        proc = subprocess.Popen(
            [cloudflared_path, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        st.session_state.cloudflared_proc = proc

        def read_output(p):
            pattern = re.compile(r'https?://[^\s\"]*trycloudflare\.com[^\s\"]*')
            for line in p.stdout:
                print(line, end='', flush=True)
                if 'website-terms' in line or 'policies' in line:
                    continue
                m = pattern.search(line)
                if m:
                    url = m.group(0)
                    st.session_state.tunnel_url_cache = url
                    try:
                        project_path("active_tunnel_url.txt").write_text(url, encoding="utf-8")
                    except Exception:
                        pass

        threading.Thread(target=read_output, args=(proc,), daemon=True).start()
    except Exception as e:
        print(f"[Cloudflared] Kon tunnel niet automatisch starten: {e}")


# Start de tunnel direct bij opstarten
start_background_tunnel(8501)

# --- WELKOMST POP-UP VOOR BÉTATESTERS (Eenmalig per sessie) ---
if "welcomed" not in st.session_state:
    st.session_state.welcomed = False


@st.dialog("👋 Welkom bij het BSI 4.1 Migratie Platform")
def welcome_popup():
    st.markdown("""
    Welkom bij de bètatester versie van het **VisMigPrediction Platform (BSI 4.1)**! 🦅

    ⚠️ **Belangrijke tip over het 120-uurs Toekomstvenster:**  
    Het opzoeken en berekenen van een volledige 120-uurs prognose kan **enkele minuten** in beslag nemen. Dit komt doordat de AI-engine meer dan **5.600+ historische tellingen** en ruim **12.000.000+ waargenomen vogels** uit de laatste 23 jaar diepgaand analyseert. 

    *💡 Wil je snel resultaat? Gebruik dan de **Live Prognose** of de **Dag-Timeline in blokken met identiek weerbeeld**!*
    """)
    if st.button("Begrepen, start de applicatie 🚀", use_container_width=True):
        st.session_state.welcomed = True
        st.rerun()


if not st.session_state.welcomed:
    welcome_popup()

sites_dna_path = project_path("sites_DNA.json")
if not sites_dna_path.exists():
    with st.spinner("🧬 Ecologisch site-DNA per telpost opbouwen op basis van alle historische data..."):
        generate_sites_dna(str(get_db_path()), str(sites_dna_path))
    st.success("✅ 'sites_DNA.json' succesvol gegenereerd en opgeslagen!")

# CSS injectie voor LUXE DARK THEME UI/UX EN RESPONSIVE CSS GRID
st.markdown("""
    <style>
        .forecast-date-header { font-size: 13px !important; font-weight: bold; color: #fff; margin-bottom: 4px; text-align: center; }

        .weather-box { 
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); 
            border: 1px solid #334155; 
            border-radius: 10px; 
            padding: 12px; 
            margin-bottom: 14px; 
            color: #f8fafc; 
            font-size: 13px; 
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.15); 
        }
        .weather-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(115px, 1fr));
            gap: 8px;
            text-align: center;
            margin-bottom: 8px;
        }
        .weather-item {
            background: rgba(255, 255, 255, 0.05);
            padding: 8px 6px;
            border-radius: 6px;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }
        .weather-val { font-weight: 800; color: #38bdf8; font-size: 15px; letter-spacing: -0.01em; }
        .weather-lbl { font-size: 9px; color: #94a3b8; text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px; margin-top: 2px; }
        .weather-sun-row {
            display: flex;
            justify-content: space-around;
            align-items: center;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
            padding-top: 8px;
            font-size: 12px;
            color: #fbbf24;
            font-weight: 500;
        }
        .wind-arrow {
            display: inline-block;
            font-size: 14px;
            font-weight: bold;
            color: #f43f5e;
        }

        .bsi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
            margin-bottom: 16px;
        }

        .bsi-card { 
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); 
            border-radius: 14px; 
            padding: 14px; 
            margin-top: 0px; 
            margin-bottom: 0px; 
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.2); 
            border: 1px solid #334155;
            border-left: 6px solid #ccc; 
            position: relative; 
            overflow: hidden; 
            transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            color: #f8fafc;
            height: 100%;
            box-sizing: border-box;
        }
        .bsi-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 20px 30px -10px rgba(0, 0, 0, 0.4), 0 10px 15px -5px rgba(0, 0, 0, 0.3);
            border-color: #475569;
        }
        .bsi-header { 
            font-size: 11px; 
            font-weight: 700; 
            text-transform: uppercase; 
            letter-spacing: 0.6px; 
            margin-bottom: 8px; 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
        }
        .bsi-ai-badge {
            background: rgba(255, 255, 255, 0.06);
            padding: 2px 6px;
            border-radius: 20px;
            font-size: 9px;
            color: #94a3b8;
            border: 1px solid rgba(255, 255, 255, 0.1);
            font-weight: 700;
        }
        .bsi-title-container { 
            display: flex; 
            align-items: center; 
            gap: 12px; 
            margin-bottom: 10px; 
        }
        .bsi-species-img { 
            width: 55px; 
            height: 55px; 
            border-radius: 8px; 
            object-fit: cover; 
            border: 1px solid #475569; 
            background-color: #0f172a; 
            flex-shrink: 0; 
            box-shadow: 0 3px 6px rgba(0,0,0,0.3);
        }
        .bsi-species-placeholder { 
            width: 55px; 
            height: 55px; 
            border-radius: 8px; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            background: rgba(255, 255, 255, 0.05); 
            font-size: 24px; 
            border: 1px solid #475569; 
            flex-shrink: 0; 
            box-shadow: 0 3px 6px rgba(0,0,0,0.3);
        }
        .bsi-title { 
            font-size: 16px; 
            font-weight: 800; 
            color: #f8fafc; 
            margin: 0; 
            line-height: 1.2; 
            letter-spacing: -0.01em;
        }
        .bsi-sub { 
            font-size: 11px; 
            color: #94a3b8; 
            font-style: italic; 
            margin-top: 2px;
            font-weight: 500;
        }

        .bsi-metrics { 
            display: flex; 
            align-items: center;
            background: rgba(255, 255, 255, 0.03); 
            padding: 8px 10px; 
            border-radius: 8px; 
            margin-bottom: 8px; 
            border: 1px solid rgba(255, 255, 255, 0.06); 
        }
        .metric-box { flex: 1; text-align: center; }
        .metric-divider { width: 1px; height: 24px; background-color: rgba(255, 255, 255, 0.1); margin: 0 6px; }
        .metric-val { font-size: 18px; font-weight: 900; color: #38bdf8; letter-spacing: -0.02em; }
        .metric-label { font-size: 9px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.8px; margin-top: 2px; }

        .peak-badge { 
            font-size: 10px; 
            color: #cbd5e1; 
            background: rgba(255, 255, 255, 0.03); 
            padding: 6px 8px; 
            border-radius: 6px; 
            margin-bottom: 8px; 
            display: inline-block; 
            width: 100%; 
            text-align: center; 
            font-weight: 600; 
            border: 1px solid rgba(255, 255, 255, 0.06);
        }
        .sparkline-wrapper {
            background: rgba(15, 23, 42, 0.6);
            border-radius: 6px;
            padding: 4px;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }
        .sparkline-img { width: 100%; height: 65px; object-fit: contain; display: block; filter: brightness(0.95); }

        .bsi-card-overlay {
            position: absolute;
            top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(15, 23, 42, 0.96);
            backdrop-filter: blur(4px);
            display: flex;
            flex-direction: column;
            justify-content: center;
            padding: 14px;
            opacity: 0;
            transition: opacity 0.25s ease-in-out;
            pointer-events: none;
            z-index: 10;
            box-sizing: border-box;
            border-radius: 14px;
            color: #f8fafc;
        }
        .bsi-card:hover .bsi-card-overlay, .bsi-card:active .bsi-card-overlay {
            opacity: 1;
            pointer-events: auto;
        }
        .overlay-title { font-size: 16px; font-weight: 800; color: #f8fafc; margin-bottom: 6px; letter-spacing: -0.01em; }
        .overlay-text { font-size: 11px; color: #cbd5e1; margin-bottom: 8px; line-height: 1.4; }
    </style>
""", unsafe_allow_html=True)


def generate_wind_sector_baseline(db_path: str, output_path: str) -> bool:
    resolver = SpeciesResolver(project_path())

    if not os.path.exists(db_path):
        st.sidebar.error(f"Database niet gevonden op pad: {db_path}")
        return False

    try:
        with sqlite3.connect(db_path) as conn:
            query = """
                    SELECT UPPER(TRIM(h.windrichting))                                                    as raw_wind,
                           h.windkracht                                                                   as raw_bft,
                           h.tellingid,
                           w.soortid,
                           CAST(strftime('%m',
                                         datetime(CAST(h.begintijd AS INTEGER), 'unixepoch')) AS INTEGER) as month_num,
                           SUM(
                                   CAST(COALESCE(w.aantal, 0) AS INTEGER) +
                                   CAST(COALESCE(w.aantalterug, 0) AS INTEGER)
                           ) as count
                    FROM waarnemingen w
                        INNER JOIN telling_headers h
                    ON w.tellingid = h.tellingid
                    WHERE h.windrichting IS NOT NULL
                      AND TRIM (h.windrichting) != ''
                      AND h.begintijd IS NOT NULL
                      AND w.soortid IS NOT NULL
                    GROUP BY h.tellingid, w.soortid, raw_wind, raw_bft, month_num
                    """
            df = pd.read_sql_query(query, conn)
    except Exception as e:
        st.sidebar.error(f"SQL Fout: {e}")
        return False

    if df.empty:
        return False

    known_intervals = WeatherManagerUtils._load_16_traps_mapping()
    valid_labels = {lbl for lbl, _, _ in known_intervals}

    def resolve_to_16_wind(val):
        if not val:
            return None
        s = str(val).strip().upper()
        norm = WeatherManagerUtils.normalize_wind_label(s)
        if norm in valid_labels:
            return norm
        try:
            return WeatherManagerUtils.deg_to_16_wind_label(float(s.replace("°", "").replace(",", ".").strip()))
        except ValueError:
            pass
        return None

    def get_bft_class(val):
        try:
            b = float(str(val).replace(",", ".").strip())
            return "0-2 Bft" if b <= 2.5 else ("3-4 Bft" if b <= 4.5 else "5+ Bft")
        except (TypeError, ValueError):
            return "Onbekend"

    df['sector'] = df['raw_wind'].apply(resolve_to_16_wind)
    df['bft_class'] = df['raw_bft'].apply(get_bft_class)
    df = df.dropna(subset=['sector'])
    df = df[df['bft_class'] != 'Onbekend']

    if df.empty:
        return False

    baseline_data = {}
    for sector, sec_group in df.groupby('sector'):
        baseline_data[sector] = {"maanden": {}}
        for month, month_group in sec_group.groupby('month_num'):
            month_str = str(int(month))
            baseline_data[sector]["maanden"][month_str] = {}
            for bft_cls, bft_group in month_group.groupby('bft_class'):
                total_teldagen = bft_group['tellingid'].nunique()
                species_grouped = bft_group.groupby('soortid').agg(
                    waarnemingsdagen=('tellingid', 'nunique'),
                    totaal_aantal=('count', 'sum')
                ).reset_index()

                species_dict = {}
                for _, row in species_grouped.iterrows():
                    sp_id = str(row['soortid']).strip()
                    species_dict[sp_id] = {
                        "naam": resolver.get_name(sp_id),
                        "latin": resolver.get_latin(sp_id),
                        "waarnemingsdagen": int(row['waarnemingsdagen']),
                        "totaal_aantal": int(row['totaal_aantal']),
                        "gemiddeld_per_telling": round(int(row['totaal_aantal']) / total_teldagen,
                                                       2) if total_teldagen > 0 else 0.0,
                        "frequentie_pct": round((int(row['waarnemingsdagen']) / total_teldagen) * 100,
                                                2) if total_teldagen > 0 else 0.0
                    }

                sorted_species = dict(
                    sorted(species_dict.items(), key=lambda item: item[1]['totaal_aantal'], reverse=True))
                baseline_data[sector]["maanden"][month_str][bft_cls] = {
                    "totaal_teldagen": int(total_teldagen),
                    "totaal_soorten": len(sorted_species),
                    "soorten": sorted_species
                }

    try:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(baseline_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


logo_path = Path("BSI_logo.png")
if logo_path.exists():
    st.sidebar.image(str(logo_path), width=140)

st.sidebar.title("Bio Statistic Intelligence")

tunnel_url = st.session_state.get('tunnel_url_cache', '')
if not tunnel_url:
    tunnel_file = project_path("active_tunnel_url.txt")
    if tunnel_file.exists():
        tunnel_url = tunnel_file.read_text(encoding="utf-8").strip()

if tunnel_url:
    st.sidebar.markdown("### 🌐 Live Bètatester Link")
    st.sidebar.caption("Deel deze link met je tester:")
    st.sidebar.code(tunnel_url, language="")
    st.sidebar.markdown("---")

st.sidebar.subheader("Navigatie")
app_mode = st.sidebar.selectbox(
    "Schakel naar",
    [
        "Prognoses",
        "Overzicht",
        "Excel Upload (.xlsx)",
        "Cluster Kaart",
        "🧭 Windroos & Weekprofielen",
        "📍 Mijn Telpost Registreren",
        "🔐 Beheer (Admin)"
    ]
)

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Databeheer & Matrix")

if st.sidebar.button("📊 Genereer Wind-Sector Baseline"):
    baseline_json_path = project_path("wind_sector_baseline.json")
    db_file_path = str(get_db_path())
    with st.spinner("⏳ Bezig met analyseren van historische tellingen..."):
        success = generate_wind_sector_baseline(db_file_path, str(baseline_json_path))
    if success:
        st.sidebar.success("✅ Baseline succesvol opgeslagen!")
    else:
        st.sidebar.error("❌ Fout bij genereren baseline.")


def calculate_distance_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return R * c


@st.cache_data
def load_sites_mapping():
    possible_paths = [
        project_path("serverdata", "sites.json"),
        project_path("VT5", "serverdata", "sites.json")
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
            except Exception:
                pass
    return mapping


@st.cache_data
def get_available_telpost_options():
    user_data = telpost_manager.laad_telpost_data()
    user_list = user_data.get("locaties", [])

    telpost_locations = load_telpost_locations()
    sites_mapping = load_sites_mapping()

    base_list = []
    if isinstance(telpost_locations, dict):
        base_list = telpost_locations.get("locaties", telpost_locations.get("json", []))
    elif isinstance(telpost_locations, list):
        base_list = telpost_locations

    seen_ids = set()
    combined_list = []
    for item in user_list + base_list:
        sid = str(item.get("telpostid", "")).strip()
        if sid and sid not in seen_ids:
            seen_ids.add(sid)
            combined_list.append(item)

    posts = []
    for item in combined_list:
        sid = str(item.get("telpostid", "")).strip()
        lat = pd.to_numeric(item.get("latitude"), errors='coerce')
        lon = pd.to_numeric(item.get("longitude"), errors='coerce')
        if sid and not math.isnan(lat) and not math.isnan(lon):
            name = item.get("Telpostnaam") or sites_mapping.get(sid, f"Telpost {sid}")
            posts.append({
                "telpostid": sid,
                "naam": name,
                "lat": lat,
                "lon": lon
            })
    return posts


@st.cache_data(ttl=3600)
def get_ecologically_filtered_cluster(selected_site_id: str, radius_site_ids: List[str]) -> List[str]:
    dna_path = Path("sites_DNA.json")
    if not dna_path.exists():
        return radius_site_ids

    try:
        with open(dna_path, "r", encoding="utf-8") as f:
            dna_data = json.load(f)
    except Exception:
        return radius_site_ids

    if selected_site_id not in dna_data:
        return radius_site_ids

    main_profile = dna_data[selected_site_id]["species_counts"]
    main_total = dna_data[selected_site_id]["total_specimens"]
    if main_total == 0:
        return radius_site_ids

    main_freqs = {sp: count / main_total for sp, count in main_profile.items()}
    filtered_sites = [selected_site_id]

    for sid in radius_site_ids:
        if sid == selected_site_id or sid not in dna_data:
            continue

        other_profile = dna_data[sid]["species_counts"]
        other_total = dna_data[sid]["total_specimens"]
        if other_total == 0:
            continue

        other_freqs = {sp: count / other_total for sp, count in other_profile.items()}
        overlap = sum(
            min(main_freqs[sp], other_freqs[sp]) for sp in set(main_freqs.keys()).intersection(set(other_freqs.keys())))

        if overlap >= 0.15:
            filtered_sites.append(sid)

    return filtered_sites


@st.cache_data(ttl=3600)
def fetch_cluster_species_profiles(
    db_path: str,
    target_date: date,
    site_ids: Optional[List[str]] = None,
    selected_site_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    day_of_year = target_date.timetuple().tm_yday
    day_start = day_of_year - 5
    day_end = day_of_year + 5

    query = """
            SELECT w.soortid,
                   SUM((CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER) + CAST(w.aantal_plus AS INTEGER) +
                       CAST(w.aantalterug_plus AS INTEGER)) *
                       CASE WHEN h.telpostid = ? THEN 1.5 ELSE 1.0 END) as count,
            AVG(CAST(NULLIF(h.temperatuur, '') AS FLOAT)) as avgTemp,
            UPPER(h.windrichting) as mainWind,
            AVG(CAST(NULLIF(h.windkracht, '') AS FLOAT)) as avgBft,
            AVG(CAST(NULLIF(h.hpa, '') AS FLOAT)) as avgPressure,
            AVG(CAST(strftime('%H', datetime(CAST(MAX(w.tijdstip, h.begintijd) AS INTEGER), 'unixepoch', 'localtime')) AS INTEGER)) as avgHour,
            MAX(CAST(w.markeren AS INTEGER)) as isRemarkable
            FROM waarnemingen w
                INNER JOIN telling_headers h
            ON w.tellingid = h.tellingid
            WHERE ((CAST (strftime('%j'
                , datetime(CAST (h.begintijd AS INTEGER)
                , 'unixepoch')) AS INTEGER) BETWEEN ?
              AND ?)
               OR (CAST (strftime('%j'
                , datetime(CAST (h.begintijd AS INTEGER)
                , 'unixepoch')) AS INTEGER) + 365 BETWEEN ?
              AND ?)
               OR (CAST (strftime('%j'
                , datetime(CAST (h.begintijd AS INTEGER)
                , 'unixepoch')) AS INTEGER) - 365 BETWEEN ?
              AND ?))
              AND h.telpostid != '5177'
            GROUP BY w.soortid
            ORDER BY count DESC
            """

    params = [
        str(selected_site_id) if selected_site_id else "",
        day_start, day_end, day_start, day_end, day_start, day_end,
    ]
    if site_ids:
        valid_site_ids = [str(site_id) for site_id in site_ids if str(site_id) != "5177"]
        if valid_site_ids:
            placeholders = ",".join("?" for _ in valid_site_ids)
            query = query.replace(
                "AND h.telpostid != '5177'",
                f"AND h.telpostid IN ({placeholders}) AND h.telpostid != '5177'",
            )
            params.extend(valid_site_ids)
        else:
            query = query.replace(
                "AND h.telpostid != '5177'",
                "AND 1 = 0",
            )
    resolver = SpeciesResolver(project_path())

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
                d["expectedIndex"] = float(d["count"]) / 100.0
                results.append(d)
            return results
    except Exception:
        return []


GILDE_KLEUREN = {
    "Roofvogels (Zwevers)": "#d9534f",
    "Roofvogels (Actief)": "#c0392b",
    "Zangvogels": "#f0ad4e",
    "Zeevogels (Pelagics)": "#0275d8",
    "Kustvogels (Zee-eenden/Duikers/Futen)": "#1abc9c",
    "Watervogels (Ganzen/Grondeleenden)": "#3498db",
    "Landvogels": "#5cb85c",
    "Speciale Landvogels": "#27ae60",
    "Reigers": "#e67e22",
    "Steltlopers": "#9b59b6",
    "Meeuwen & Sterns": "#e84393",
    "Ooievaars (Zwevers)": "#d35400",
    "Insecten": "#16a085",
    "Zoogdieren": "#8e44ad"
}


def render_species_card(card_data, cluster_site_ids, dt_target, image_manager) -> str:
    bc = GILDE_KLEUREN.get(card_data.guild_name, "#5cb85c")
    img_data_uri = image_manager.get_species_image_base64(card_data.latin_name)
    img_html = f'<img src="{img_data_uri}" class="bsi-species-img" alt="{card_data.latin_name}">' if img_data_uri else '<div class="bsi-species-placeholder">🦅</div>'

    weekly_rows = fetch_species_weekly_distribution(card_data.soortid, cluster_site_ids)
    norm_buf = SparklineEngine.prepare_normalized_buffer(weekly_rows)
    spark_uri = SparklineEngine.get_sparkline_base64(norm_buf, target_dt=dt_target)
    spark_html = f'<img src="{spark_uri}" class="sparkline-img" alt="Fenologie">'

    large_spark_uri = SparklineEngine.get_sparkline_base64(norm_buf, target_dt=dt_target, width_px=320, height_px=90)
    large_spark_html = f'<img src="{large_spark_uri}" style="width:100%; border-radius:6px; margin-top:6px;" alt="Uitvergrote Fenologie">'

    val = card_data.norm_score_ex_h
    if val < 0.05:
        score_str = f"{val:.3f}"
        rare_note_html = '<div style="font-size: 8.5px; color: #ef4444; font-weight: 700; text-transform: uppercase; margin-top: 4px; letter-spacing: 0.3px; text-align: center;">⚠️ Zeldzame soort, ooit waargenomen in deze periode</div>'
    else:
        score_str = f"{val:.1f}"
        rare_note_html = ''

    return (
        f'<div class="bsi-card" style="border-left-color: {bc};">'
        f'<div class="bsi-card-overlay">'
        f'<div class="overlay-title">🔍 {card_data.soortnaam}</div>'
        f'<div class="overlay-text"><b>Gilde:</b> {card_data.guild_name}<br>'
        f'<b>AI Model:</b> {card_data.sources_label} (Heur: {card_data.heuristic_prob}% | Proto: {card_data.prototype_prob}%)<br>'
        f'<b>Norm Score:</b> {val:.4f} ex/u<br>'
        f'<b>Voorjaar Piek:</b> {card_data.spring_peak}<br>'
        f'<b>Najaar Piek:</b> {card_data.autumn_peak}</div>'
        f'{large_spark_html}'
        f'</div>'
        f'<div class="bsi-header">'
        f'<span style="color: {bc};">🛡️ {card_data.guild_name}</span>'
        f'<span class="bsi-ai-badge">H: {card_data.heuristic_prob}% &nbsp;|&nbsp; P: {card_data.prototype_prob}%</span>'
        f'</div>'
        f'<div class="bsi-title-container">'
        f'{img_html}'
        f'<div>'
        f'<div class="bsi-title">{card_data.soortnaam}</div>'
        f'<div class="bsi-sub">{card_data.latin_name}</div>'
        f'</div>'
        f'</div>'
        f'<div class="bsi-metrics">'
        f'<div class="metric-box">'
        f'<div class="metric-val" style="color: #38bdf8;">{card_data.display_prob}%</div>'
        f'<div class="metric-label">BSI Kans</div>'
        f'</div>'
        f'<div class="metric-divider"></div>'
        f'<div class="metric-box">'
        f'<div class="metric-val" style="color: #f8fafc;">{score_str}</div>'
        f'<div class="metric-label">ex. / uur</div>'
        f'</div>'
        f'</div>'
        f'{rare_note_html}'
        f'<div class="peak-badge" style="margin-top: 6px;">📅 <b>Voorjaar:</b> {card_data.spring_peak} &nbsp;&bull;&nbsp; <b>Najaar:</b> {card_data.autumn_peak}</div>'
        f'<div class="sparkline-wrapper">{spark_html}</div>'
        f'</div>'
    )


def render_grouped_species_cards(items, evaluator, image_manager, cluster_site_ids, dt_target):
    if not items:
        st.write("Geen significante trek verwacht in dit tijdsvenster.")
        return

    evaluated_cards = []
    for item in items:
        card_data = evaluator.build_comparative_card(item, item, cluster_site_ids)
        if card_data:
            evaluated_cards.append({
                "card_data": card_data,
                "guild": card_data.guild_name,
                "score": card_data.display_prob
            })

    if not evaluated_cards:
        return

    guild_groups = {}
    for ec in evaluated_cards:
        g = ec["guild"]
        guild_groups.setdefault(g, []).append(ec)

    for g in guild_groups:
        guild_groups[g].sort(key=lambda x: x["score"], reverse=True)

    guild_max_scores = {g: max(ec["score"] for ec in cards) for g, cards in guild_groups.items()}
    sorted_guilds = sorted(guild_groups.keys(), key=lambda g: guild_max_scores[g], reverse=True)

    for guild_name in sorted_guilds:
        bc = GILDE_KLEUREN.get(guild_name, "#5cb85c")
        st.markdown(
            f'<div style="font-size: 13px; font-weight: 800; color: {bc}; text-transform: uppercase; margin-top: 24px; margin-bottom: 10px; letter-spacing: 0.8px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 4px;">🛡️ {guild_name}</div>',
            unsafe_allow_html=True
        )

        cards_html_list = []
        for ec in guild_groups[guild_name]:
            card_html = render_species_card(ec["card_data"], cluster_site_ids, dt_target, image_manager)
            if card_html:
                cards_html_list.append(card_html)

        if cards_html_list:
            grid_html = '<div class="bsi-grid">' + "".join(cards_html_list) + '</div>'
            st.markdown(grid_html, unsafe_allow_html=True)


def render_weather_box(block):
    b_deg = block.get('wind_deg', 0)
    try:
        b_deg_val = int(round(float(b_deg)))
    except (TypeError, ValueError):
        b_deg_val = 0
    rot_deg = (b_deg_val + 180) % 360

    temp = block.get('temp', 15)
    try:
        temp_val = int(round(float(temp)))
    except (TypeError, ValueError):
        temp_val = 15

    wind_label = block.get('wind_label', 'W')
    wind_bft = block.get('wind_bft', 2)
    try:
        bft_val = int(round(float(wind_bft)))
    except (TypeError, ValueError):
        bft_val = 2

    pressure = block.get('pressure', 1016)
    try:
        pressure_val = int(round(float(pressure)))
    except (TypeError, ValueError):
        pressure_val = 1016

    precip_mm = block.get('precip_mm', 0.0)
    try:
        precip_val = float(precip_mm)
    except (TypeError, ValueError):
        precip_val = 0.0

    precip_prob = block.get('precip_prob', 0)

    cloud_percent = block.get('cloud_cover', 10)
    try:
        cloud_val = float(cloud_percent)
    except (TypeError, ValueError):
        cloud_val = 10.0

    cloud_octaves = max(0, min(8, int(round((cloud_val / 100.0) * 8))))
    cloud_display_str = f"{cloud_val:.2f}% - {cloud_octaves}/8"

    sunrise = block.get('sunrise', '06:00')
    sunset = block.get('sunset', '20:00')
    corridor_boost = block.get('corridor_boost', None)

    corridor_html = f'<span>🌍 Corridor Boost: <b>+{int(corridor_boost * 100)}%</b></span>' if corridor_boost is not None else ''

    weather_box_html = (
        f'<div class="weather-box">'
        f'<div class="weather-grid">'
        f'<div class="weather-item"><div class="weather-val">{temp_val}°C</div><div class="weather-lbl">Temperatuur</div></div>'
        f'<div class="weather-item"><div class="weather-val">{wind_label} {bft_val}Bft</div><div class="weather-lbl">Windkracht</div></div>'
        f'<div class="weather-item"><div class="weather-val"><span class="wind-arrow" style="transform: rotate({rot_deg}deg); display: inline-block;">↑</span> {b_deg_val}°</div><div class="weather-lbl">Windrichting</div></div>'
        f'<div class="weather-item"><div class="weather-val">{pressure_val} hPa</div><div class="weather-lbl">Luchtdruk</div></div>'
        f'<div class="weather-item"><div class="weather-val">{precip_val:.2f} mm</div><div class="weather-lbl">Neerslag ({precip_prob}%)</div></div>'
        f'<div class="weather-item"><div class="weather-val">{cloud_display_str}</div><div class="weather-lbl">Bewolking</div></div>'
        f'</div>'
        f'<div class="weather-sun-row"><span>🌅 Zonsopgang: <b>{sunrise}</b></span>{corridor_html}<span>🌇 Zonsondergang: <b>{sunset}</b></span></div>'
        f'</div>'
    )
    st.markdown(weather_box_html, unsafe_allow_html=True)


if app_mode == "Overzicht":
    st.header("📋 Systeemstatus & Data-integratie")
    db_status, db_path = check_database()
    if not db_status:
        st.error(f"❌ Kan SQLite database niet vinden op: {db_path}")
    else:
        st.success("✅ Lokale SQLite Room-database is gekoppeld.")

elif app_mode == "Excel Upload (.xlsx)":
    st.header("📤 Upload Teldata van Telpost")
    uploaded_files = st.file_uploader("Sleep je .xlsx bestanden hierheen", type=["xlsx", "xls"],
                                      accept_multiple_files=True)
    if uploaded_files:
        handle_excel_upload(uploaded_files)

elif app_mode == "Prognoses":
    header_logo_path = Path("BSI_logo.png")
    if header_logo_path.exists():
        with open(header_logo_path, "rb") as f:
            encoded_header_logo = base64.b64encode(f.read()).decode("utf-8")
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 1.5rem;">
                <img src="data:image/png;base64,{encoded_header_logo}" style="width: 38px; height: 38px; object-fit: contain;">
                <h1 style="margin: 0; padding: 0; font-size: 2rem; font-weight: 700; color: inherit; letter-spacing: -0.02em;">BSI 4.1 Migratie Prognose</h1>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.header("BSI 4.1 Migratie Prognoses")

    mode_choice = st.radio(
        "Selecteer Modus",
        ["Live Prognose (Enkele Datum)", "+5 Dagen (120-Uur in Weer-Blokken)", "Dag-Timeline (in Weer-blokken)"],
        horizontal=True
    )

    all_telposts = get_available_telpost_options()
    formatted_telpost_options = [f"{p['telpostid']} - {p['naam']}" for p in all_telposts] if all_telposts else [
        "4310 - Spanjaardduinen"]

    col_p1, col_p2 = st.columns(2)
    with col_p1:
        selected_telpost_str = st.selectbox("Selecteer Hoofdtelpost", formatted_telpost_options)
    with col_p2:
        if mode_choice.startswith("Live") or mode_choice.startswith("Dag-Timeline"):
            prognose_datum = st.date_input("Datum voor prognose", value=datetime.now())

    selected_telpost_id = selected_telpost_str.split(" - ")[0]

    telpost_data_json = telpost_manager.laad_telpost_data()
    raw_locs = telpost_data_json.get("locaties", [])
    current_post_meta = next((loc for loc in raw_locs if str(loc.get("telpostid")) == str(selected_telpost_id)), {})
    is_coastal_post = current_post_meta.get("Is_Coastal_Post", False)

    if is_coastal_post:
        st.info(
            "🌊 **Kusttelpost geselecteerd:** Deze post is gemarkeerd met zicht op open zee (Pelagische soorten worden meegenomen in de prognose).")

    main_lat, main_lon = 52.05, 4.25
    raw_cluster_ids = [selected_telpost_id]

    if all_telposts:
        main_post_obj = next((p for p in all_telposts if str(p['telpostid']) == str(selected_telpost_id)), None)
        if main_post_obj:
            main_lat, main_lon = main_post_obj['lat'], main_post_obj['lon']
            raw_cluster_ids = []
            for p in all_telposts:
                dist = calculate_distance_km(main_lat, main_lon, p['lat'], p['lon'])
                if dist <= 35.0:
                    raw_cluster_ids.append(str(p['telpostid']))

    cluster_site_ids = get_ecologically_filtered_cluster(selected_telpost_id, raw_cluster_ids)

    resolver = SpeciesResolver(project_path())
    neural_engine = None
    neural_model_data = load_neural_engine()
    if neural_model_data:
        try:
            neural_engine = LiteNeuralEngine.from_dict(neural_model_data)
        except (KeyError, TypeError, ValueError):
            neural_engine = None

    expert_kb = None
    expert_path = project_path("AI-models", "expert_knowledge.json")
    if expert_path.exists():
        try:
            expert_kb = ExpertKnowledgeBase.from_dict(
                json.loads(expert_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, TypeError):
            expert_kb = None

    db_path_str = get_db_path()
    evaluator = CardEvaluator(db_path_str, resolver)
    image_manager = SpeciesImageManager(db_path_str)

    if mode_choice.startswith("Live"):
        if st.button("Genereer Live BSI Prognose"):
            st.success(
                f"✅ BSI Engine gestart voor telpost **{selected_telpost_str}** met ecologisch gefilterd cluster ({len(cluster_site_ids)} zusterposten)!")

            with st.spinner("Actueel live weer van dit moment opvragen en 2-uurs venster doorrekenen..."):
                now_dt = datetime.now()
                forecast_sys = BsiForecastSystem(
                    db_path_str,
                    resolver,
                    neural_engine=neural_engine,
                    expert_kb=expert_kb,
                )
                forecast_data = forecast_sys.fetch_5day_weather_forecast(main_lat, main_lon)

                w_sample = None
                next_sample = None
                if forecast_data and "hourly" in forecast_data:
                    hourly_list = forecast_data["hourly"]
                    for idx, h in enumerate(hourly_list):
                        if h["time"].startswith(now_dt.strftime("%Y-%m-%dT%H")):
                            w_sample = h
                            if idx + 1 < len(hourly_list):
                                next_sample = hourly_list[idx + 1]
                            break
                    if not w_sample and hourly_list:
                        w_sample = hourly_list[0]
                        next_sample = hourly_list[1] if len(hourly_list) > 1 else w_sample

                if w_sample:
                    t_vals = [w_sample["temp"]]
                    w_speeds = [w_sample["wind_speed"]]
                    w_degs = [w_sample["wind_deg"]]
                    press = [w_sample["pressure"]]
                    clouds = [w_sample["cloud_cover"]]
                    precips = [w_sample["precip_mm"]]
                    probs = [w_sample["precip_prob"]]

                    if next_sample:
                        t_vals.append(next_sample["temp"])
                        w_speeds.append(next_sample["wind_speed"])
                        w_degs.append(next_sample["wind_deg"])
                        press.append(next_sample["pressure"])
                        clouds.append(next_sample["cloud_cover"])
                        precips.append(next_sample["precip_mm"])
                        probs.append(next_sample["precip_prob"])

                    avg_temp = sum(t_vals) / len(t_vals)
                    avg_speed = sum(w_speeds) / len(w_speeds)
                    avg_deg = sum(w_degs) / len(w_degs)
                    avg_press = sum(press) / len(press)
                    avg_cloud = sum(clouds) / len(clouds)
                    total_precip = sum(precips)
                    max_prob = max(probs) if probs else 0

                    wind_lbl = WeatherManagerUtils.deg_to_16_wind_label(avg_deg)
                    wind_bft_val = WeatherManagerUtils.ms_to_beaufort(avg_speed)

                    end_dt = now_dt + timedelta(hours=2)
                    block_label = f"Live 2-Uur Venster: {now_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')} ({wind_lbl} {wind_bft_val}Bft)"

                    weather = WeatherContext(
                        lat=main_lat,
                        lon=main_lon,
                        temp=avg_temp,
                        wind_speed=avg_speed,
                        wind_deg=avg_deg,
                        cloud_percent=avg_cloud,
                        pressure=avg_press,
                        visibility=10000,
                        pressure_trend=0.0
                    )

                    sun_info = forecast_data.get("sun_map", {}).get(now_dt.strftime("%Y-%m-%d"), {})
                    live_block = {
                        "time_block": block_label,
                        "temp": avg_temp,
                        "wind_label": wind_lbl,
                        "wind_bft": wind_bft_val,
                        "wind_deg": avg_deg,
                        "pressure": int(round(avg_press)),
                        "precip_mm": total_precip,
                        "precip_prob": max_prob,
                        "cloud_cover": avg_cloud,
                        "sunrise": sun_info.get("sunrise_str", "06:30"),
                        "sunset": sun_info.get("sunset_str", "20:15")
                    }
                else:
                    weather = AiWeatherService.fetch_contextual_weather(main_lat, main_lon)
                    if not weather:
                        weather = WeatherContext(lat=main_lat, lon=main_lon, temp=15.0, wind_speed=5.0, wind_deg=45.0,
                                                 cloud_percent=4.0, pressure=1016.0, visibility=10000,
                                                 pressure_trend=1.0)
                    wind_lbl = WeatherManagerUtils.deg_to_16_wind_label(
                        weather.wind_deg) if weather.wind_deg is not None else "W"
                    wind_bft_val = WeatherManagerUtils.ms_to_beaufort(
                        weather.wind_speed) if weather.wind_speed is not None else 3
                    end_dt = now_dt + timedelta(hours=2)
                    live_block = {
                        "time_block": f"Live Huidig Moment ({now_dt.strftime('%H:%M')} - {end_dt.strftime('%H:%M')})",
                        "temp": weather.temp if weather.temp is not None else 15.0,
                        "wind_label": wind_lbl,
                        "wind_bft": wind_bft_val,
                        "wind_deg": weather.wind_deg if weather.wind_deg is not None else 0.0,
                        "pressure": int(round(weather.pressure if weather.pressure is not None else 1016.0)),
                        "precip_mm": 0.0,
                        "precip_prob": 0,
                        "cloud_cover": weather.cloud_percent if weather.cloud_percent is not None else 10.0,
                        "sunrise": "06:30",
                        "sunset": "20:15"
                    }

                st.markdown(
                    f"### ⚡ Snelle Live 2-Uurs Prognose ({now_dt.strftime('%d-%m-%Y %H:%M')} tot {(now_dt + timedelta(hours=2)).strftime('%H:%M')})")
                render_weather_box(live_block)

                dt_target = now_dt
                species_profiles = fetch_cluster_species_profiles(
                    db_path_str,
                    now_dt.date(),
                    site_ids=cluster_site_ids,
                    selected_site_id=selected_telpost_id,
                )

                if not species_profiles:
                    st.warning("⚠️ Geen waarnemingen gevonden binnen dit fenologische venster.")
                else:
                    suggesties = AiInferenceEngine.calculate_bsi_prognosis(
                        lat=main_lat,
                        lon=main_lon,
                        dt=dt_target,
                        weather=weather,
                        species_profiles=species_profiles,
                        neural_engine=neural_engine,
                        model_labels=resolver.model_labels,
                        expert_kb=expert_kb,
                    )
                    if not suggesties:
                        st.warning("⚠️ Geen enkele soort voldeed aan de kwaliteitsdrempel (15%).")
                    else:
                        st.success(f"🎯 {len(suggesties)} soorten/taxa succesvol doorgerekend en gegroepeerd per gilde!")
                        render_grouped_species_cards(suggesties, evaluator, image_manager, cluster_site_ids, dt_target)

    elif mode_choice.startswith("Dag-Timeline"):
        if st.button("Genereer Dag-Timeline (Zonsopgang - Zonsondergang)"):
            dt_target = datetime.combine(prognose_datum, datetime.min.time())
            with st.spinner("Zonnestand berekenen en dagelijkse weervensters doorrekenen..."):
                forecast_sys = BsiForecastSystem(
                    db_path_str,
                    resolver,
                    neural_engine=neural_engine,
                    expert_kb=expert_kb,
                )
                timeline_blocks = forecast_sys.generate_daily_timeline_prognosis(main_lat, main_lon, cluster_site_ids,
                                                                                 dt_target,
                                                                                 selected_site_id=selected_telpost_id)

                if not timeline_blocks:
                    st.warning("⚠️ Kon geen timeline genereren voor deze datum.")
                else:
                    st.success(f"✅ Dag-timeline succesvol geladen ({len(timeline_blocks)} tijdblokken)!")
                    tab_labels = [block["time_block"] for block in timeline_blocks]
                    tabs = st.tabs(tab_labels)
                    for idx, tab in enumerate(tabs):
                        block = timeline_blocks[idx]
                        with tab:
                            render_weather_box(block)
                            render_grouped_species_cards(block["top_species"], evaluator, image_manager,
                                                         cluster_site_ids, dt_target)

    else:
        if st.button("Genereer 120-Uur prognose"):
            with st.spinner("120-uurs weersvoorspelling, zonnestanden en tijdblokken doorrekenen..."):
                forecast_sys = BsiForecastSystem(
                    db_path_str,
                    resolver,
                    neural_engine=neural_engine,
                    expert_kb=expert_kb,
                )
                five_day_timeline = forecast_sys.generate_5day_timeline_prognosis(
                    main_lat,
                    main_lon,
                    cluster_site_ids,
                    selected_site_id=selected_telpost_id,
                )

                if not five_day_timeline:
                    st.warning("⚠️ Kon geen 5-daagse tijdlijn genereren.")
                else:
                    st.success("✅ 120-Uurs prognose succesvol geladen!")
                    day_tab_labels = [datetime.strptime(day_data['date_str'], "%Y-%m-%d").strftime("%d-%m-%Y") for
                                      day_data in five_day_timeline]
                    day_tabs = st.tabs(day_tab_labels)

                    for day_idx, day_tab in enumerate(day_tabs):
                        day_data = five_day_timeline[day_idx]
                        with day_tab:
                            blocks = day_data["blocks"]
                            if not blocks:
                                st.write("Geen daglichtblokken beschikbaar.")
                                continue
                            block_tab_labels = [b["time_block"] for b in blocks]
                            block_tabs = st.tabs(block_tab_labels)
                            for b_idx, block_tab in enumerate(block_tabs):
                                block = blocks[b_idx]
                                with block_tab:
                                    render_weather_box(block)
                                    dt_item = datetime.strptime(day_data['date_str'], "%Y-%m-%d")
                                    render_grouped_species_cards(block["top_species"], evaluator, image_manager,
                                                                 cluster_site_ids, dt_item)

# --- PAGINA: CLUSTER KAART ---
elif app_mode == "Cluster Kaart":
    st.header("🗺️ Telposten & Cluster Visualisatie")
    posts_list = get_available_telpost_options()

    if not posts_list:
        st.warning("⚠️ Geen locaties gevonden.")
    else:
        posts_df = pd.DataFrame(posts_list)
        names_list = posts_df['naam'].tolist()

        if "cluster_selected_name" not in st.session_state:
            st.session_state.cluster_selected_name = names_list[0] if names_list else ""

        if st.session_state.cluster_selected_name not in names_list and names_list:
            st.session_state.cluster_selected_name = names_list[0]

        current_index = names_list.index(
            st.session_state.cluster_selected_name) if st.session_state.cluster_selected_name in names_list else 0

        selected_name = st.selectbox(
            "Selecteer Hoofdtelpost",
            names_list,
            index=current_index,
            key="cluster_selectbox"
        )

        if selected_name != st.session_state.cluster_selected_name:
            st.session_state.cluster_selected_name = selected_name
            st.rerun()

        main_row = posts_df[posts_df['naam'] == st.session_state.cluster_selected_name].iloc[0]
        main_lat, main_lon = main_row['lat'], main_row['lon']

        m = folium.Map(location=[main_lat, main_lon], zoom_start=10, control_scale=True)
        folium.TileLayer('openstreetmap', name='Standaard (OSM)').add_to(m)

        cluster_posts = []
        for _, row in posts_df.iterrows():
            dist = calculate_distance_km(main_lat, main_lon, row['lat'], row['lon'])
            if dist <= 35.0:
                cluster_posts.append(row)

        for row in cluster_posts:
            is_main = (row['naam'] == st.session_state.cluster_selected_name)
            circle_color = '#e74c3c' if is_main else '#2ecc71'
            circle_opacity = 0.08 if is_main else 0.04

            folium.Circle(
                location=[row['lat'], row['lon']],
                radius=35000,
                color=circle_color,
                weight=2 if is_main else 1,
                fill=True,
                fill_color=circle_color,
                fill_opacity=circle_opacity,
                tooltip=f"35 km straal rond {row['naam']}"
            ).add_to(m)

        for _, row in posts_df.iterrows():
            dist = calculate_distance_km(main_lat, main_lon, row['lat'], row['lon'])
            is_main = (row['naam'] == st.session_state.cluster_selected_name)
            marker_color = 'red' if is_main else ('green' if dist <= 35.0 else 'blue')
            icon_name = 'star' if is_main else ('ok-sign' if dist <= 35.0 else 'info-sign')

            folium.Marker(
                location=[row['lat'], row['lon']],
                popup=f"<b>{row['naam']}</b><br>ID: {row['telpostid']}<br>Afstand tot hoofdtelpost: {dist:.1f} km",
                tooltip=row['naam'],
                icon=folium.Icon(color=marker_color, icon=icon_name, prefix='glyphicon')
            ).add_to(m)

        folium.LayerControl().add_to(m)

        map_data = st_folium(m, width=1200, height=550, key="cluster_interactive_map")

        if map_data:
            clicked_name = None

            if map_data.get("last_object_clicked"):
                obj = map_data["last_object_clicked"]
                if obj.get("tooltip") in names_list:
                    clicked_name = obj.get("tooltip")
                elif obj.get("popup"):
                    match = re.search(r'<b>(.*?)<\/b>', obj.get("popup"))
                    if match:
                        parsed_name = match.group(1).strip()
                        if parsed_name in names_list:
                            clicked_name = parsed_name

            if not clicked_name and map_data.get("last_clicked"):
                c_lat = map_data["last_clicked"]["lat"]
                c_lon = map_data["last_clicked"]["lng"]
                closest_post = None
                min_dist = float('inf')
                for _, row in posts_df.iterrows():
                    d = calculate_distance_km(c_lat, c_lon, row['lat'], row['lon'])
                    if d < min_dist:
                        min_dist = d
                        closest_post = row
                if closest_post is not None and min_dist < 5.0:
                    clicked_name = closest_post['naam']

            if clicked_name and clicked_name != st.session_state.cluster_selected_name:
                st.session_state.cluster_selected_name = clicked_name
                st.rerun()

elif app_mode == "📍 Mijn Telpost Registreren":
    telpost_manager.render_telpost_registratie_interface()

elif app_mode == "🧭 Windroos & Weekprofielen":
    telpost_manager.render_windroos_weekprofielen()

# --- PAGINA: BEHEER ADMIN (Beveiligd met hardcoded wachtwoord) ---
elif app_mode == "🔐 Beheer (Admin)":
    st.header("🔐 Beveiligde Beheeromgeving")

    if "admin_ingelogd" not in st.session_state:
        st.session_state.admin_ingelogd = False

    if not st.session_state.admin_ingelogd:
        st.warning("Voer het beheerwachtwoord in om toegang te krijgen tot het telpostbeheer.")
        gekozen_wachtwoord = st.text_input("Wachtwoord", type="password", key="admin_pwd_input")

        if st.button("Inloggen"):
            if gekozen_wachtwoord == "YvesAtVisMigPred":
                st.session_state.admin_ingelogd = True
                st.success("✅ Toegang verleend!")
                st.rerun()
            else:
                st.error("❌ Onjuist wachtwoord.")
    else:
        st.success("🔓 Je bent succesvol ingelogd als beheerder.")
        if st.button("Uitloggen"):
            st.session_state.admin_ingelogd = False
            st.rerun()

        st.markdown("---")
        # Roep hier de werkelijke beheer-interface aan uit de telpost_manager module
        telpost_manager.render_beheer_pagina()