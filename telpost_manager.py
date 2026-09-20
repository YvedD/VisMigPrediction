import json
import os
import time
import sqlite3
import pandas as pd
import streamlit as st
import folium
import altair as alt
from streamlit_folium import st_folium
from app_paths import project_path
from db_manager import get_db_path
from bsi.species_resolver import SpeciesResolver
from bsi.weather_service import WeatherManagerUtils

# Correct pad naar de submap serverdata
DATA_FILE = project_path("serverdata", "telpost_locaties.json")
GRAPH_BACKGROUND = "#739B9B"


def laad_telpost_data():
    """Laadt de telposten uit serverdata/telpost_locaties.json."""
    if not DATA_FILE.exists():
        return {"locaties": []}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for loc in data.get("locaties", []):
                if "Telpostnaam" not in loc:
                    loc["Telpostnaam"] = f"Telpost {loc.get('telpostid', 'Onbekend')}"
                if "Is_Coastal_Post" not in loc:
                    loc["Is_Coastal_Post"] = False
            return data
    except Exception as e:
        st.error(f"Fout bij het laden van telpost data: {e}")
        return {"locaties": []}


def sla_telpost_data(data):
    """Slaat de telposten op in serverdata/telpost_locaties.json."""
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        st.error(f"Fout bij het opslaan van telpost data: {e}")
        return False


def render_windroos_weekprofielen():
    """Toon de 16-traps windprofielen voor alle gebruikers."""
    st.subheader("🧭 Windroos & Weekprofielen")
    db_path = get_db_path()
    if not os.path.exists(db_path):
        st.error(f"Database niet gevonden op: {db_path}")
        return

    st.markdown(
        "Kies een vogelsoort en telpost. De grafieken tonen de som van alle waargenomen "
        "exemplaren per week, samengevoegd over alle beschikbare teljaren."
    )
    st.info(
        "**Belangrijk:** deze grafieken tonen niet de vliegrichting van de vogels. "
        "De 16 windrichtingen geven aan uit welke richting de wind kwam op het moment "
        "van de waarneming. De waarden tonen vervolgens hoeveel exemplaren bij die "
        "specifieke windrichting werden waargenomen."
    )
    resolver = SpeciesResolver(project_path())
    species_options = {
        f"{item.soortnaam} (ID: {item.soortid})": item.soortid
        for item in sorted(
            resolver.species_by_id.values(),
            key=lambda item: item.soortnaam.casefold(),
        )
        if item.soortnaam
    }
    locations = laad_telpost_data().get("locaties", [])
    windpost_options = {"🌍 Alle telposten (Geheel databestand)": "ALLE"}
    for loc in locations:
        site_name = loc.get("Telpostnaam", f"Telpost {loc['telpostid']}").strip()
        site_id = str(loc["telpostid"])
        windpost_options[f"{site_name} (ID: {site_id})"] = site_id

    wind_col1, wind_col2 = st.columns(2)
    with wind_col1:
        selected_species_label = st.selectbox(
            "Selecteer vogelsoort",
            list(species_options.keys()),
            key="public_wind_profile_species",
        )
        selected_species_id = species_options[selected_species_label]
    with wind_col2:
        selected_windpost_label = st.selectbox(
            "Selecteer Telpost",
            list(windpost_options.keys()),
            key="public_wind_profile_telpost",
        )
        selected_windpost_id = windpost_options[selected_windpost_label]

    if not st.button("Genereer 16 windroosgrafieken 🧭", type="primary"):
        return

    wind_query = """
        SELECT UPPER(TRIM(h.windrichting)) AS raw_wind,
               CAST(strftime('%W', datetime(CAST(h.begintijd AS INTEGER),
               'unixepoch', 'localtime')) AS INTEGER) + 1 AS week_num,
               SUM(COALESCE(w.aantal, 0) + COALESCE(w.aantalterug, 0)) AS totaal_aantal
        FROM waarnemingen w
        INNER JOIN telling_headers h ON w.tellingid = h.tellingid
        WHERE w.soortid = ?
          AND h.windrichting IS NOT NULL
          AND TRIM(h.windrichting) != ''
          AND h.begintijd IS NOT NULL
          AND h.begintijd != ''
    """
    wind_params = [selected_species_id]
    if selected_windpost_id != "ALLE":
        wind_query += " AND h.telpostid = ?"
        wind_params.append(selected_windpost_id)
    wind_query += " GROUP BY raw_wind, week_num ORDER BY week_num ASC"

    try:
        with sqlite3.connect(db_path) as conn:
            wind_df = pd.read_sql_query(wind_query, conn, params=wind_params)

        wind_intervals = WeatherManagerUtils._load_16_traps_mapping()
        wind_labels = [label for label, _, _ in wind_intervals]

        def resolve_wind_sector(value):
            raw_value = str(value).strip().upper()
            normalized_value = raw_value.replace("°", "").replace(",", ".").strip()
            try:
                return WeatherManagerUtils.deg_to_16_wind_label(float(normalized_value))
            except ValueError:
                return WeatherManagerUtils.normalize_wind_label(raw_value)

        wind_df["sector"] = wind_df["raw_wind"].apply(resolve_wind_sector)
        wind_df = wind_df[wind_df["sector"].isin(wind_labels)].copy()
        if wind_df.empty:
            st.warning("Geen geldige 16-traps windrichtingen gevonden. De grafieken worden met nullen getoond.")
            profile_df = pd.DataFrame(columns=["sector", "week_num", "totaal_aantal"])
        else:
            wind_df["week_num"] = pd.to_numeric(wind_df["week_num"], errors="coerce").astype("Int64")
            wind_df["totaal_aantal"] = pd.to_numeric(
                wind_df["totaal_aantal"], errors="coerce"
            ).fillna(0)
            profile_df = wind_df.groupby(
                ["sector", "week_num"], as_index=False
            )["totaal_aantal"].sum()

        month_names = [
            "Januari", "Februari", "Maart", "April", "Mei", "Juni",
            "Juli", "Augustus", "September", "Oktober", "November", "December",
        ]
        week_numbers = pd.Index(range(1, 54), name="week_num")
        week_frame = pd.DataFrame({"week_num": week_numbers})
        week_frame["week_start"] = pd.to_datetime("2024-01-01") + pd.to_timedelta(
            week_frame["week_num"] - 1, unit="W"
        )
        week_frame["month_name"] = week_frame["week_start"].dt.month.map(
            dict(enumerate(month_names, start=1))
        )
        week_frame["week_label"] = "Week " + week_frame["week_num"].astype(str)
        st.success(
            f"✅ Windroosprofiel geladen voor **{resolver.get_name(selected_species_id)}** "
            f"({selected_windpost_label})."
        )

        graph_columns = st.columns(2)
        for index, sector in enumerate(wind_labels):
            sector_df = profile_df[profile_df["sector"] == sector]
            month_totals = (
                sector_df.set_index("week_num")["totaal_aantal"]
                if not sector_df.empty
                else pd.Series(dtype="float64")
            )
            chart_data = week_frame.copy()
            chart_data["Totaal"] = month_totals.reindex(
                week_numbers, fill_value=0
            ).astype(float).to_numpy()
            with graph_columns[index % 2]:
                st.markdown(f"**{sector}**")
                chart_source = chart_data.reset_index(drop=True)
                month_axis = alt.Axis(
                    title="Maanden / weken",
                    tickCount=53,
                    labelExpr=(
                        "date(datum.value) <= 7 ? "
                        "['Januari', 'Februari', 'Maart', 'April', 'Mei', 'Juni', "
                        "'Juli', 'Augustus', 'September', 'Oktober', 'November', 'December']"
                        "[month(datum.value)] : ''"
                    ),
                    labelAngle=-35,
                    labelOverlap=False,
                    labelLimit=110,
                    tickSize=5,
                    tickWidth=1,
                    tickColor="rgba(148,163,184,0.8)",
                    labelColor="#D1D5DB",
                    titleColor="#D1D5DB",
                )
                chart_encoding = {
                    "x": alt.X("week_start:T", axis=month_axis),
                    "y": alt.Y(
                        "Totaal:Q",
                        scale=alt.Scale(zero=True),
                        axis=alt.Axis(
                            title="Exemplaren",
                            labelColor="#D1D5DB",
                            titleColor="#D1D5DB",
                        ),
                    ),
                    "tooltip": [
                        alt.Tooltip("week_label:N", title="Week"),
                        alt.Tooltip("month_name:N", title="Maand"),
                        alt.Tooltip("Totaal:Q", title="Exemplaren"),
                    ],
                }
                area = alt.Chart(chart_source).mark_area(
                    line=False,
                    color=alt.Gradient(
                        gradient="linear",
                        stops=[
                            alt.GradientStop(color="rgba(220,38,38,0.60)", offset=0),
                            alt.GradientStop(color="rgba(220,38,38,0.00)", offset=1),
                        ],
                        x1=1, x2=1, y1=0, y2=1,
                    ),
                ).encode(**chart_encoding)
                week_markers = alt.Chart(chart_source).mark_rule(
                    color="#7AA4A4", strokeWidth=1
                ).encode(x=alt.X("week_start:T", axis=month_axis))
                line = alt.Chart(chart_source).mark_line(
                    color="#DC2626", strokeWidth=1.15, interpolate="monotone"
                ).encode(**chart_encoding)
                chart = (
                    (area + week_markers + line)
                    .properties(
                        height=440,
                        background="#000000",
                        padding={"left": 12, "right": 12, "top": 12, "bottom": 8},
                    )
                    .configure_view(
                        fill=GRAPH_BACKGROUND,
                        stroke="rgba(148,163,184,0.45)",
                        strokeWidth=1,
                    )
                    .configure_axis(
                        gridColor="#355858",
                        gridOpacity=0.7,
                        gridWidth=1,
                        domainColor="rgba(148,163,184,0.65)",
                        tickColor="rgba(148,163,184,0.65)",
                        labelColor="#D1D5DB",
                        titleColor="#D1D5DB",
                    )
                )
                st.altair_chart(chart, use_container_width=True)
    except Exception as e:
        st.error(f"Fout bij genereren windroosgrafieken: {e}")


def render_telpost_registratie_interface():
    """Interface met 4 invoervelden naast elkaar en live kaartintegratie."""
    st.subheader("📍 Telpost Registratie & Beheer")
    st.markdown(
        "Voeg hieronder je telpost toe of pas coördinaten aan. Alle geregistreerde posten worden op de kaart getoond.")

    if "reg_lat" not in st.session_state:
        st.session_state.reg_lat = 51.215000
    if "reg_lon" not in st.session_state:
        st.session_state.reg_lon = 2.935000

    data = laad_telpost_data()
    locaties = data.get("locaties", [])

    # 4 kolommen netjes naast elkaar op één rij
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        telpostnaam = st.text_input("Telpostnaam", value=st.session_state.get("reg_naam", ""),
                                    placeholder="bijv. Bredene Strand", key="input_naam")
        st.session_state.reg_naam = telpostnaam
    with col2:
        telpostid = st.text_input("Telpostnummer (ID)", value=st.session_state.get("reg_id", ""),
                                  placeholder="bijv. 4310", key="input_id")
        st.session_state.reg_id = telpostid
    with col3:
        lat_input = st.number_input("Latitude", value=float(st.session_state.reg_lat), format="%.6f", step=0.000001,
                                    key="input_lat")
        if lat_input != st.session_state.reg_lat:
            st.session_state.reg_lat = lat_input
    with col4:
        lon_input = st.number_input("Longitude", value=float(st.session_state.reg_lon), format="%.6f", step=0.000001,
                                    key="input_lon")
        if lon_input != st.session_state.reg_lon:
            st.session_state.reg_lon = lon_input

    is_coastal = st.checkbox("Is een kusttelpost (Pelagische soortobservaties)",
                             value=st.session_state.get("reg_coastal", False), key="input_coastal")
    st.session_state.reg_coastal = is_coastal

    st.markdown("---")
    st.markdown("**🗺️ Kaartoverzicht (Bestaande telposten in blauw, huidige selectie in rood)**")

    m = folium.Map(location=[st.session_state.reg_lat, st.session_state.reg_lon], zoom_start=11)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satelliet',
        overlay=False,
        control=True
    ).add_to(m)

    # Toon alle opgeslagen posten uit het bestand
    for loc in locaties:
        try:
            lat = float(loc["latitude"])
            lon = float(loc["longitude"])
            name = loc.get("Telpostnaam", f"Telpost {loc['telpostid']}")
            sid = loc['telpostid']
            coastal_status = "Ja 🌊" if loc.get("Is_Coastal_Post", False) else "Nee 🌳"
            folium.Marker(
                [lat, lon],
                popup=f"<b>{name}</b><br>ID: {sid}<br>Kustpost: {coastal_status}",
                tooltip=name,
                icon=folium.Icon(color="blue", icon="info-sign")
            ).add_to(m)
        except Exception:
            pass

    # Marker voor huidige selectie
    folium.Marker(
        [st.session_state.reg_lat, st.session_state.reg_lon],
        popup=f"Selectie: {st.session_state.reg_lat:.5f}, {st.session_state.reg_lon:.5f}",
        tooltip="Nieuwe / te bewerken locatie",
        icon=folium.Icon(color="red", icon="map-marker")
    ).add_to(m)

    folium.LayerControl().add_to(m)

    map_data = st_folium(m, width=700, height=400, key="telpost_interactive_map")

    if map_data and map_data.get("last_clicked"):
        clicked_lat = map_data["last_clicked"]["lat"]
        clicked_lon = map_data["last_clicked"]["lng"]
        if clicked_lat != st.session_state.reg_lat or clicked_lon != st.session_state.reg_lon:
            st.session_state.reg_lat = clicked_lat
            st.session_state.reg_lon = clicked_lon
            st.rerun()

    st.markdown("---")
    if st.button("💾 Telpost Definitief Opslaan", type="primary", use_container_width=True):
        current_naam = st.session_state.get("reg_naam", "").strip()
        current_id = str(st.session_state.get("reg_id", "")).strip()

        if not current_naam or not current_id:
            st.error("Vul alstublieft zowel de Telpostnaam als het Telpostnummer in.")
        else:
            timestamp_ms = int(time.time() * 1000)
            bestaande_index = next((i for i, item in enumerate(locaties) if str(item["telpostid"]) == current_id), None)

            nieuwe_item = {
                "telpostid": current_id,
                "latitude": float(st.session_state.reg_lat),
                "longitude": float(st.session_state.reg_lon),
                "timestamp": timestamp_ms,
                "Telpostnaam": current_naam,
                "Is_Coastal_Post": bool(st.session_state.get("reg_coastal", False))
            }

            if bestaande_index is not None:
                locaties[bestaande_index] = nieuwe_item
                st.success(f"✅ Telpost '{current_naam}' (ID: {current_id}) succesvol bijgewerkt in serverdata!")
            else:
                locaties.append(nieuwe_item)
                st.success(f"✅ Telpost '{current_naam}' (ID: {current_id}) succesvol toegevoegd aan serverdata!")

            data["locaties"] = locaties
            sla_telpost_data(data)


def render_beheer_pagina():
    """Geavanceerd beheerscherm met tabs voor CRUD, Jaarlijkse Database Analyses en Grafieken."""
    st.subheader("🔐 Beheerderspagina (Admin)")

    admin_paswoord = "YvesAtVisMigPred"
    try:
        if hasattr(st, "secrets") and "ADMIN_PASSWORD" in st.secrets:
            admin_paswoord = st.secrets["ADMIN_PASSWORD"]
    except Exception:
        pass

    ingevoerd_paswoord = st.text_input("Voer beheerderswachtwoord in:", type="password", key="admin_pwd_box")

    if ingevoerd_paswoord == admin_paswoord:
        st.success("✅ Toegang verleend tot het geavanceerde beheerpaneel.")

        # Tabs voor verschillende beheertaken
        tab1, tab2, tab3 = st.tabs(
            ["📍 Telposten Beheer (CRUD)", "📊 Jaaroverzicht & Query", "🧭 Windroos & Weekprofielen"])

        data = laad_telpost_data()
        locaties = data.get("locaties", [])

        # --- TAB 1: TELPOSTEN BEHEER ---
        with tab1:
            st.write(f"Totaal aantal geregistreerde telposten: {len(locaties)}")
            if locaties:
                df_locs = pd.DataFrame(locaties)
                st.dataframe(df_locs, width='stretch')

                st.markdown("### Telpost Bewerken of Verwijderen")
                selected_id = st.selectbox("Selecteer Telpost ID om te beheren", [loc["telpostid"] for loc in locaties],
                                           key="beheer_select_id")

                huidige_post = next((loc for loc in locaties if str(loc["telpostid"]) == str(selected_id)), None)

                if huidige_post:
                    with st.form("wijzig_telpost_form"):
                        w_naam = st.text_input("Telpostnaam", value=huidige_post.get("Telpostnaam", ""))
                        w_lat = st.number_input("Latitude", value=float(huidige_post.get("latitude", 52.0)),
                                                format="%.6f")
                        w_lon = st.number_input("Longitude", value=float(huidige_post.get("longitude", 4.2)),
                                                format="%.6f")
                        w_coastal = st.checkbox("Kusttelpost", value=huidige_post.get("Is_Coastal_Post", False))

                        col_b1, col_b2 = st.columns(2)
                        with col_b1:
                            update_btn = st.form_submit_button("💾 Wijzigingen Opslaan")
                        with col_b2:
                            delete_btn = st.form_submit_button("🗑️ Verwijder Telpost", type="primary")

                        if update_btn:
                            huidige_post["Telpostnaam"] = w_naam
                            huidige_post["latitude"] = w_lat
                            huidige_post["longitude"] = w_lon
                            huidige_post["Is_Coastal_Post"] = w_coastal
                            sla_telpost_data(data)
                            st.success(f"✅ Telpost {selected_id} bijgewerkt!")
                            st.rerun()

                        if delete_btn:
                            data["locaties"] = [loc for loc in locaties if str(loc["telpostid"]) != str(selected_id)]
                            sla_telpost_data(data)
                            st.success(f"🗑️ Telpost {selected_id} verwijderd!")
                            st.rerun()

        # --- TAB 2: JAAROVERZICHT PER TELPOST & SOORT ---
        with tab2:
            st.subheader("📊 Jaaroverzicht per Telpost & Vogelsoort")
            st.markdown(
                "Kies een specifieke telpost (of alle telposten) en optioneel een vogelsoort om de historische aantallen per jaar te bekijken.")

            db_path = get_db_path()

            if not os.path.exists(db_path):
                st.error(f"Database niet gevonden op: {db_path}")
            else:
                resolver = SpeciesResolver(project_path())

                # Telpost selectie opties samenstellen
                telpost_opties = {"🌍 Alle telposten (Geheel databestand)": "ALLE"}
                for loc in locaties:
                    t_naam = loc.get("Telpostnaam", f"Telpost {loc['telpostid']}")
                    t_id = str(loc["telpostid"])
                    telpost_opties[f"{t_naam} (ID: {t_id})"] = t_id

                col_q1, col_q2 = st.columns(2)
                with col_q1:
                    gekozen_label = st.selectbox("Selecteer Telpost", list(telpost_opties.keys()),
                                                 key="query_telpost_select")
                    geselecteerde_telpost_id = telpost_opties[gekozen_label]
                with col_q2:
                    soort_filter = st.text_input("Vogelsoortnaam of ID (optioneel, laat leeg voor alle soorten)",
                                                 placeholder="bijv. Kluut, Zomertortel of 135", key="query_soort_input")

                if st.button("Genereer Jaaroverzicht 📊", type="primary"):
                    target_soortid = None
                    query_valid = True

                    # Automatische naam-naar-ID resolutie via SpeciesResolver
                    if soort_filter and soort_filter.strip():
                        clean_filter = soort_filter.strip()
                        if clean_filter in resolver.species_by_id:
                            target_soortid = clean_filter
                        else:
                            target_soortid = resolver.resolve_id(clean_filter)

                        if not target_soortid:
                            st.warning(
                                f"⚠️ Soort '{clean_filter}' kon niet worden gevonden. Controleer de spelling of probeer het soort-ID (bijv. '135').")
                            query_valid = False

                    if query_valid:
                        # Bouw dynamische query die per jaar groepeert over het volledige databestand
                        query = """
                                SELECT strftime('%Y', \
                                                datetime(CAST(h.begintijd AS INTEGER), 'unixepoch', 'localtime')) as jaar, \
                                       SUM(COALESCE(w.aantal, 0) + COALESCE(w.aantalterug, 0))                    as totaal_aantal
                                FROM waarnemingen w
                                         INNER JOIN telling_headers h ON w.tellingid = h.tellingid
                                WHERE h.begintijd IS NOT NULL \
                                  AND h.begintijd != ''
                                """
                        params = []

                        # Filter op telpost indien niet "ALLE" is geselecteerd
                        if geselecteerde_telpost_id != "ALLE":
                            query += " AND h.telpostid = ?"
                            params.append(geselecteerde_telpost_id)

                        # Filter op soort indien ingevuld
                        if target_soortid:
                            query += " AND w.soortid = ?"
                            params.append(target_soortid)

                        query += " GROUP BY jaar ORDER BY jaar ASC"

                        try:
                            with sqlite3.connect(db_path) as conn:
                                df_res = pd.read_sql_query(query, conn, params=params)

                            if df_res.empty or df_res['jaar'].dropna().empty:
                                st.warning("⚠️ Geen waarnemingen gevonden voor deze selectie in de database.")
                            else:
                                # Opschonen en sorteren van de jaartallen
                                df_res = df_res.dropna(subset=['jaar'])
                                df_res['jaar'] = df_res['jaar'].astype(str)
                                # GECORRIGEERD: errors='coerce' i.p.v. errors='fill_value=0'
                                df_res['totaal_aantal'] = pd.to_numeric(df_res['totaal_aantal'],
                                                                        errors='coerce').fillna(0)

                                soort_tekst = f" voor soort **{resolver.get_name(target_soortid)}**" if target_soortid else " voor **alle soorten**"
                                st.success(f"✅ Jaaroverzicht succesvol geladen{soort_tekst}!")

                                # Visualisatie: Grafiek per jaar
                                chart_source = df_res.rename(
                                    columns={
                                        "jaar": "Jaar",
                                        "totaal_aantal": "Totaal",
                                    }
                                )
                                yearly_chart = (
                                    alt.Chart(chart_source)
                                    .mark_bar(color="#38bdf8")
                                    .encode(
                                        x=alt.X("Jaar:N", title="Jaar"),
                                        y=alt.Y("Totaal:Q", title="Waarnemingen"),
                                        tooltip=[
                                            alt.Tooltip("Jaar:N", title="Jaar"),
                                            alt.Tooltip("Totaal:Q", title="Waarnemingen"),
                                        ],
                                    )
                                    .properties(background=GRAPH_BACKGROUND)
                                    .configure_view(stroke=None)
                                )
                                st.altair_chart(yearly_chart, use_container_width=True)

                                # Gedetailleerde tabel eronder
                                st.markdown("### 📋 Cijfers per Jaar")
                                df_display = df_res.copy()
                                df_display.columns = ['Jaar', 'Totaal Aantal Waarnemingen']
                                st.dataframe(df_display, width='stretch')

                        except Exception as e:
                            st.error(f"Fout bij uitvoeren query: {e}")

        # --- TAB 3: WINDROOS & WEEKPROFIELEN ---
        with tab3:
            st.subheader("🧭 Windroos & Weekprofielen")
            db_path = get_db_path()

            if os.path.exists(db_path):
                st.subheader("🧭 Weekprofiel per 16-traps windrichting")
                st.markdown(
                    "Kies een vogelsoort en telpost. De grafieken tonen de som van alle waargenomen exemplaren "
                    "per week, samengevoegd over alle beschikbare teljaren."
                )

                resolver = SpeciesResolver(project_path())
                species_options = {
                    f"{item.soortnaam} (ID: {item.soortid})": item.soortid
                    for item in sorted(
                        resolver.species_by_id.values(),
                        key=lambda item: item.soortnaam.casefold(),
                    )
                    if item.soortnaam
                }
                windpost_options = {"🌍 Alle telposten (Geheel databestand)": "ALLE"}
                for loc in locaties:
                    site_name = loc.get("Telpostnaam", f"Telpost {loc['telpostid']}").strip()
                    site_id = str(loc["telpostid"])
                    windpost_options[f"{site_name} (ID: {site_id})"] = site_id

                wind_col1, wind_col2 = st.columns(2)
                with wind_col1:
                    selected_species_label = st.selectbox(
                        "Selecteer vogelsoort",
                        list(species_options.keys()),
                        key="wind_profile_species",
                    )
                    selected_species_id = species_options[selected_species_label]
                with wind_col2:
                    selected_windpost_label = st.selectbox(
                        "Selecteer Telpost",
                        list(windpost_options.keys()),
                        key="wind_profile_telpost",
                    )
                    selected_windpost_id = windpost_options[selected_windpost_label]

                if st.button("Genereer 16 windroosgrafieken 🧭", type="primary"):
                    wind_query = """
                                  SELECT UPPER(TRIM(h.windrichting)) AS raw_wind,
                                         CAST(strftime(
                                             '%W',
                                             datetime(CAST(h.begintijd AS INTEGER), 'unixepoch', 'localtime')
                                         ) AS INTEGER) + 1 AS week_num,
                                         SUM(
                                             COALESCE(w.aantal, 0) +
                                             COALESCE(w.aantalterug, 0)
                                         ) AS totaal_aantal
                                  FROM waarnemingen w
                                  INNER JOIN telling_headers h ON w.tellingid = h.tellingid
                                  WHERE w.soortid = ?
                                    AND h.windrichting IS NOT NULL
                                    AND TRIM(h.windrichting) != ''
                                    AND h.begintijd IS NOT NULL
                                    AND h.begintijd != ''
                                  """
                    wind_params = [selected_species_id]
                    if selected_windpost_id != "ALLE":
                        wind_query += " AND h.telpostid = ?"
                        wind_params.append(selected_windpost_id)
                    wind_query += " GROUP BY raw_wind, week_num ORDER BY week_num ASC"

                    try:
                        with sqlite3.connect(db_path) as conn:
                            wind_df = pd.read_sql_query(
                                wind_query,
                                conn,
                                params=wind_params,
                            )

                        wind_intervals = WeatherManagerUtils._load_16_traps_mapping()
                        wind_labels = [label for label, _, _ in wind_intervals]

                        def resolve_wind_sector(value):
                            raw_value = str(value).strip().upper()
                            normalized_value = raw_value.replace("°", "").replace(",", ".").strip()
                            try:
                                return WeatherManagerUtils.deg_to_16_wind_label(float(normalized_value))
                            except ValueError:
                                return WeatherManagerUtils.normalize_wind_label(raw_value)

                        wind_df["sector"] = wind_df["raw_wind"].apply(resolve_wind_sector)
                        wind_df = wind_df[wind_df["sector"].isin(wind_labels)].copy()

                        month_names = [
                            "Januari", "Februari", "Maart", "April", "Mei", "Juni",
                            "Juli", "Augustus", "September", "Oktober", "November", "December",
                        ]
                        if wind_df.empty:
                            st.warning(
                                "Geen waarnemingen met een geldige 16-traps windrichting gevonden "
                                "voor deze soort en telpost. De grafieken worden met nullen getoond."
                            )
                            profile_df = pd.DataFrame(
                                columns=["sector", "week_num", "totaal_aantal"]
                            )
                        else:
                            wind_df["week_num"] = pd.to_numeric(
                                wind_df["week_num"], errors="coerce"
                            ).astype("Int64")
                            wind_df["totaal_aantal"] = pd.to_numeric(
                                wind_df["totaal_aantal"], errors="coerce"
                            ).fillna(0)
                            profile_df = wind_df.groupby(
                                ["sector", "week_num"], as_index=False
                            )["totaal_aantal"].sum()

                        # Gebruik een vast referentiejaar met maandag als eerste dag.
                        # Hierdoor vallen alle weeknummers op dezelfde x-positie,
                        # ongeacht het oorspronkelijke teljaar.
                        week_numbers = pd.Index(range(1, 54), name="week_num")
                        week_frame = pd.DataFrame({"week_num": week_numbers})
                        week_frame["week_start"] = pd.to_datetime("2024-01-01") + pd.to_timedelta(
                            week_frame["week_num"] - 1, unit="W"
                        )
                        week_frame["month_name"] = week_frame["week_start"].dt.month.map(
                            dict(enumerate(month_names, start=1))
                        )
                        week_frame["week_label"] = "Week " + week_frame["week_num"].astype(str)

                        if not wind_df.empty:
                            st.success(
                                f"✅ Windroosprofiel geladen voor **{resolver.get_name(selected_species_id)}** "
                                f"({selected_windpost_label})."
                            )
                        graph_columns = st.columns(2)
                        for index, sector in enumerate(wind_labels):
                            sector_df = profile_df[profile_df["sector"] == sector]
                            month_totals = (
                                sector_df.set_index("week_num")["totaal_aantal"]
                                if not sector_df.empty
                                else pd.Series(dtype="float64")
                            )
                            chart_data = week_frame.copy()
                            chart_data["Totaal"] = (
                                month_totals.reindex(week_numbers, fill_value=0)
                                .astype(float)
                                .to_numpy()
                            )

                            with graph_columns[index % 2]:
                                st.markdown(f"**{sector}**")
                                chart_source = chart_data.reset_index(drop=True)
                                month_axis = alt.Axis(
                                    title="Maanden / weken",
                                    tickCount=53,
                                    labelExpr=(
                                        "date(datum.value) <= 7 ? "
                                        "['Januari', 'Februari', 'Maart', 'April', "
                                        "'Mei', 'Juni', 'Juli', 'Augustus', "
                                        "'September', 'Oktober', 'November', 'December']"
                                        "[month(datum.value)] : ''"
                                    ),
                                    labelAngle=-35,
                                    labelOverlap=False,
                                    labelLimit=110,
                                    tickSize=5,
                                    tickWidth=1,
                                    tickColor="rgba(148,163,184,0.8)",
                                    labelColor="#D1D5DB",
                                    titleColor="#D1D5DB",
                                )
                                chart_encoding = {
                                    "x": alt.X(
                                        "week_start:T",
                                        axis=month_axis,
                                    ),
                                    "y": alt.Y(
                                        "Totaal:Q",
                                        scale=alt.Scale(zero=True),
                                        axis=alt.Axis(
                                            title="Exemplaren",
                                            labelColor="#D1D5DB",
                                            titleColor="#D1D5DB",
                                        ),
                                    ),
                                    "tooltip": [
                                        alt.Tooltip("week_label:N", title="Week"),
                                        alt.Tooltip("month_name:N", title="Maand"),
                                        alt.Tooltip("Totaal:Q", title="Exemplaren"),
                                    ],
                                }
                                area = alt.Chart(chart_source).mark_area(
                                    line=False,
                                    color=alt.Gradient(
                                        gradient="linear",
                                        stops=[
                                            alt.GradientStop(color="rgba(220,38,38,0.45)", offset=0),
                                            alt.GradientStop(color="rgba(220,38,38,0.00)", offset=1),
                                        ],
                                        x1=1,
                                        x2=1,
                                        y1=0,
                                        y2=1,
                                    ),
                                ).encode(**chart_encoding)
                                week_markers = alt.Chart(chart_source).mark_rule(
                                    color="#7AA4A4",
                                    strokeWidth=1,
                                ).encode(
                                    x=alt.X("week_start:T", axis=month_axis),
                                )
                                line = alt.Chart(chart_source).mark_line(
                                    color="#DC2626",
                                    strokeWidth=1.15,
                                    interpolate="monotone",
                                ).encode(**chart_encoding)
                                chart = (
                                    (area + week_markers + line)
                                    .properties(
                                        height=440,
                                        background="#000000",
                                        padding={"left": 12, "right": 12, "top": 12, "bottom": 8},
                                    )
                                    .configure_view(
                                        fill=GRAPH_BACKGROUND,
                                        stroke="rgba(148,163,184,0.45)",
                                        strokeWidth=1,
                                    )
                                    .configure_axis(
                                        gridColor="#355858",
                                        gridOpacity=0.7,
                                        gridWidth=1,
                                        domainColor="rgba(148,163,184,0.65)",
                                        tickColor="rgba(148,163,184,0.65)",
                                        labelColor="#D1D5DB",
                                        titleColor="#D1D5DB",
                                    )
                                )
                                st.altair_chart(chart, use_container_width=True)
                    except Exception as e:
                        st.error(f"Fout bij genereren windroosgrafieken: {e}")

    elif ingevoerd_paswoord:
        st.error("❌ Onjuist wachtwoord.")