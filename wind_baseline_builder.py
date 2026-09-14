"""
wind_baseline_builder.py
Berekent de historische Empirische Wind-Soorten Matrix per 16-traps windroos-sector
en slaat dit op als 'wind_sector_baseline.json'.
"""

import sqlite3
import json
import pandas as pd
from pathlib import Path
from app_paths import project_path
from bsi.weather_service import WeatherManagerUtils
from bsi.species_resolver import SpeciesResolver


def generate_wind_sector_baseline(db_path: str, output_path: str) -> bool:
    resolver = SpeciesResolver(project_path())
    known_labels = [lbl for lbl, _, _ in WeatherManagerUtils._load_16_traps_mapping()]

    try:
        with sqlite3.connect(db_path) as conn:
            query = """
                SELECT 
                    h.windrichting,
                    h.telpostid,
                    h.tellingid,
                    w.soortid,
                    SUM(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER) + CAST(w.aantal_plus AS INTEGER) + CAST(w.aantalterug_plus AS INTEGER)) as count
                FROM waarnemingen w
                INNER JOIN telling_headers h ON w.tellingid = h.tellingid
                WHERE h.windrichting IS NOT NULL AND h.windrichting != ''
                GROUP BY h.tellingid, w.soortid, h.windrichting, h.telpostid
            """
            df = pd.read_sql_query(query, conn)
    except Exception as e:
        print(f"[WindBaseline] Database fout bij inlezen: {e}")
        return False

    if df.empty:
        return False

    # Hulpfunctie om elke windrichting (tekst of graden) te mappen naar de 16-traps windroos
    def resolve_sector(val):
        if val is None:
            return None
        s_val = str(val).strip()
        try:
            deg = float(s_val.replace("°", "").replace(",", "."))
            return WeatherManagerUtils.deg_to_16_wind_label(deg)
        except ValueError:
            pass

        norm = WeatherManagerUtils.normalize_wind_label(s_val)
        if norm in known_labels:
            return norm
        return None

    df['sector'] = df['windrichting'].apply(resolve_sector)
    df = df.dropna(subset=['sector'])

    baseline_data = {}

    for sector, group in df.groupby('sector'):
        total_teldagen = group['tellingid'].nunique()
        species_grouped = group.groupby('soortid').agg(
            waarnemingsdagen=('tellingid', 'nunique'),
            totaal_aantal=('count', 'sum')
        ).reset_index()

        species_dict = {}
        for _, row in species_grouped.iterrows():
            sp_id = str(row['soortid'])
            name = resolver.get_name(sp_id)
            latin = resolver.get_latin(sp_id)
            w_dagen = int(row['waarnemingsdagen'])
            t_aantal = float(row['totaal_aantal'])
            gem_per_telling = round(t_aantal / total_teldagen, 2) if total_teldagen > 0 else 0.0

            species_dict[sp_id] = {
                "naam": name,
                "latin": latin,
                "waarnemingsdagen": w_dagen,
                "totaal_aantal": t_aantal,
                "gemiddeld_per_telling": gem_per_telling,
                "frequentie_pct": round((w_dagen / total_teldagen) * 100, 2) if total_teldagen > 0 else 0.0
            }

        # Sorteer op totaal aantal descending (meest talrijke bovenaan)
        sorted_species = dict(sorted(species_dict.items(), key=lambda item: item[1]['totaal_aantal'], reverse=True))

        baseline_data[sector] = {
            "totaal_teldagen": int(total_teldagen),
            "soorten": sorted_species
        }

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(baseline_data, f, indent=4, ensure_ascii=False)
        print(f"[WindBaseline] Succesvol opgeslagen op: {output_path}")
        return True
    except Exception as e:
        print(f"[WindBaseline] Fout bij wegschrijven JSON: {e}")
        return False