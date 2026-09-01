import re
import pandas as pd
import streamlit as st
from model import BSIModelEngine
from weather_manager import ensure_weather_archived


def handle_excel_upload(uploaded_files):
  """Verwerkt de volledige batch-import, valideert de bestanden,

  activeert de Open-Meteo weersverrijking, draait de volledige model-pipeline
  voor alle jaren/telposten, en toont een geconsolideerd master-rapport.
  """
  try:
    if not uploaded_files:
      return

    headers = {}
    datas = {}

    header_pattern = re.compile(
        r"Trektellen_headerdata_(\d+)_(\d{4})\.xlsx$", re.IGNORECASE
    )
    data_pattern = re.compile(
        r"Trektellen_data_(\d+)_(\d{4})\.xlsx$", re.IGNORECASE
    )

    for file in uploaded_files:
      filename = file.name
      match_h = header_pattern.match(filename)
      match_d = data_pattern.match(filename)

      if match_h:
        telpost_id, jaartal = match_h.groups()
        headers[(telpost_id, jaartal)] = file
      elif match_d:
        telpost_id, jaartal = match_d.groups()
        datas[(telpost_id, jaartal)] = file

    all_keys = sorted(list(set(headers.keys()).union(set(datas.keys()))))
    complete_pairs = [k for k in all_keys if k in headers and k in datas]

    st.markdown("---")
    st.subheader("📊 Batch-Import & Full-Run Model Overzicht")
    st.info(
        f"Geldige en complete koppeltjes gevonden: **{len(complete_pairs)}**"
        " teljaren."
    )

    if complete_pairs:
      summary_table = []
      for telpost_id, jaartal in complete_pairs:
        summary_table.append({
            "Telpost ID": telpost_id,
            "Jaartal": jaartal,
            "Header Bestand": headers[(telpost_id, jaartal)].name,
            "Data Bestand": datas[(telpost_id, jaartal)].name,
        })
      st.dataframe(pd.DataFrame(summary_table), use_container_width=True)

      if st.button("🚀 Start Full-Run Batch Import, Weather Enrichment & LNE"):
        status_container = st.status(
            "⏳ Bezig met Full-Run batch-verwerking...", expanded=True
        )

        batch_summary = []
        all_predictions = []
        engine = BSIModelEngine()
        total = len(complete_pairs)

        for idx, (telpost_id, jaartal) in enumerate(complete_pairs):
          status_container.update(
              label=(
                  f"[{idx+1}/{total}] Verwerken Telpost {telpost_id} voor jaar"
                  f" {jaartal}..."
              ),
              state="running",
          )

          # 1. Weersverrijking controleren / ophalen via Open-Meteo archief
          success = ensure_weather_archived(telpost_id, jaartal)
          if success:
            status_container.write(
                f"✅ Weerarchief voor telpost {telpost_id} ({jaartal}) geverifieerd."
            )
          else:
            status_container.write(
                f"⚠️ Weerarchief kon niet worden opgehaald voor telpost {telpost_id}."
            )

          # 2. Inlezen bestanden
          df_header = pd.read_excel(headers[(telpost_id, jaartal)])
          df_data = pd.read_excel(datas[(telpost_id, jaartal)])

          # 3. Voer de Lite Neural Engine & BSI model pipeline uit voor deze set
          df_preds = engine.process_observations(df_data, telpost_id, jaartal)
          if not df_preds.empty:
            all_predictions.append(df_preds)

          batch_summary.append({
              "Telpost ID": telpost_id,
              "Jaar": jaartal,
              "Sessies": len(df_header),
              "Waarnemingen": len(df_data),
              "Weer Status": "Geverifieerd" if success else "Mislukt",
              "Voorspellingen": len(df_preds),
          })

        status_container.update(
            label="🎉 Full-run batch-verwerking volledig afgerond!",
            state="complete",
            expanded=False,
        )

        st.success("📋 Batch Uitvoeringsrapport:")
        st.dataframe(pd.DataFrame(batch_summary), use_container_width=True)

        if all_predictions:
          master_df = pd.concat(all_predictions, ignore_index=True)
          st.markdown("---")
          st.subheader(
              "🏆 Master BSI Voorspellingen Rapport (Alle Telposten & Jaren)"
          )
          st.dataframe(master_df, use_container_width=True)

  except Exception as e:
    st.error(f"Fout tijdens de full-run batch verwerking: {e}")