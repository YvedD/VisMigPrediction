import streamlit as st
from config_loader import (
    load_neural_engine,
    load_species,
    load_telpost_locations,
)
from db_manager import (
    check_database,
    fetch_phenology_profile,
    fetch_training_data,
    get_table_list,
)
from parsers import handle_excel_upload

# Pagina instellingen
st.set_page_config(page_title="VisMigPrediction Platform", layout="wide")

st.title("🦅 VisMigPrediction - Platform")

# Sidebar navigatie
st.sidebar.title("Navigatie")
app_mode = st.sidebar.selectbox(
    "Kies een optie", ["Overzicht", "Excel Upload (.xlsx)", "Prognoses"]
)

# --- PAGINA 1: OVERZICHT ---
if app_mode == "Overzicht":
  st.header("📋 Systeemstatus & Data-integratie")

  # 1. Database status check
  db_status, db_path = check_database()
  if not db_status:
    st.error(f"❌ Kan SQLite database niet vinden op: {db_path}")
  else:
    st.success("✅ Lokale SQLite Room-database is gekoppeld.")

  # 2. JSON Bestanden Status Check
  st.markdown("---")
  st.subheader("📁 JSON Configuratie & Model Bestanden")

  col1, col2, col3 = st.columns(3)

  with col1:
    species_data = load_species()
    if species_data:
      st.success(f"✅ species.json geladen ({len(species_data)} soorten)[cite: 4, 11]")
    else:
      st.warning("⚠️ species.json niet gevonden in 'serverdata/'[cite: 4, 11]")

  with col2:
    telpost_data = load_telpost_locations()
    if telpost_data:
      st.success(
          f"✅ telpost_locaties.json geladen ({len(telpost_data)} telposten)[cite: 5, 11]"
      )
    else:
      st.warning(
          "⚠️ telpost_locaties.json niet gevonden in 'serverdata/'[cite: 5, 11]"
      )

  with col3:
    neural_weights = load_neural_engine()
    if neural_weights:
      st.success("✅ neural_engine.json (LNE gewichten) geladen[cite: 6, 11]")
    else:
      st.warning("⚠️ neural_engine.json niet gevonden[cite: 6, 11]")

  # --- TEST KNOPPEN ---
  st.markdown("---")
  st.subheader("🧪 Test Omgeving")

  if st.button("🚀 Test Database Queries"):
    with st.spinner("Gegevens ophalen uit SQLite..."):
      df_train = fetch_training_data(limit=5)
      df_pheno = fetch_phenology_profile()

      st.write("### Training Data Preview:")
      st.dataframe(df_train, use_container_width=True)

      st.write("### Fenologisch Profiel Preview:")
      st.dataframe(df_pheno, use_container_width=True)

# --- PAGINA 2: EXCEL UPLOAD ---
elif app_mode == "Excel Upload (.xlsx)":
  st.header("📤 Upload Teldata van Telpost")
  st.write(
      "Selecteer of sleep **beide** bij elkaar behorende bestanden tegelijk"
      " (`Trektellen_headerdata_[id]_[jaar].xlsx` en"
      " `Trektellen_data_[id]_[jaar].xlsx`)."
  )

  # Meerdere bestanden tegelijk accepteren
  uploaded_files = st.file_uploader(
      "Sleep je .xlsx bestanden hierheen", type=["xlsx", "xls"], accept_multiple_files=True
  )

  if uploaded_files:
    handle_excel_upload(uploaded_files)

# --- PAGINA 3: PROGNOSES ---
elif app_mode == "Prognoses":
  st.header("📈 Migratie Prognoses")
  st.info("Hier komen straks de modelberekeningen op basis van het weer.")