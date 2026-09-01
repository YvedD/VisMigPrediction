import json
import os
import numpy as np
import pandas as pd
import streamlit as st


def sigmoid(x):
  """Activatie-functie voor het neurale netwerk (tussen 0.0 en 1.0)[cite: 11]."""
  return 1 / (1 + np.exp(-np.clip(x, -500, 500)))


class LiteNeuralEnginePredictor:

  def __init__(self):
    self.weights_in_hidden, self.bias_hidden, self.weights_hidden_out, self.bias_output = (
        self._load_model_weights()
    )

  def _load_model_weights(self):
    """Laadt de MLP gewichten en biassen uit neural_engine.json[cite: 10, 11]."""
    path = os.path.join("AI-models", "neural_engine.json")
    if os.path.exists(path):
      with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        w_in = np.array(data.get("wInputHidden", []))
        b_hid = np.array(data.get("bHidden", []))
        w_out = np.array(data.get("wHiddenOutput", []))
        b_out = np.array(data.get("bOutput", []))
        return w_in, b_hid, w_out, b_out
    return None, None, None, None

  def predict(self, feature_vector):
    """Voert een forward pass uit door de Lite Neural Engine (LNE)[cite: 10, 11]."""
    if self.weights_in_hidden is None or self.weights_hidden_out is None:
      return 0.5  # Fallback score

    try:
      features = np.array(feature_vector, dtype=float)
      expected_len = self.weights_in_hidden.shape[0]

      if len(features) < expected_len:
        features = np.pad(features, (0, expected_len - len(features)), "constant")
      else:
        features = features[:expected_len]

      hidden_input = np.dot(features, self.weights_in_hidden) + self.bias_hidden
      hidden_output = sigmoid(hidden_input)

      final_input = (
          np.dot(hidden_output, self.weights_hidden_out) + self.bias_output
      )
      final_output = sigmoid(final_input)

      return float(np.mean(final_output))
    except Exception as e:
      print(f"Fout tijdens LNE berekening: {e}")
      return 0.5


class BSIModelEngine:

  def __init__(self):
    self.lne = LiteNeuralEnginePredictor()

  def calculate_day_circularity(self, date_val):
    """Berekent dag-circulariteit (sin/cos)[cite: 11, 12]."""
    try:
      dt = pd.to_datetime(date_val)
      day_of_year = dt.dayofyear
    except:
      day_of_year = 150

    sin_val = np.sin(2 * np.pi * day_of_year / 365)
    cos_val = np.cos(2 * np.pi * day_of_year / 365)
    return sin_val, cos_val

  def apply_guild_multiplier(self, species_name, wind_bft, precipitation):
    """Expert Rules / Guilds interpretatie[cite: 1, 11, 12]."""
    thermal_species = ["Buizerd", "Ooievaar", "Wespendief", "Bruine Kiekendief"]
    if species_name in thermal_species:
      if wind_bft > 4 or precipitation > 0:
        return 0.1
    return 1.0

  def build_feature_vector(self, row):
    """Bouwt de AI Input Feature Vector[cite: 11, 12]."""
    date_val = row.get("date", "2023-01-01")
    sin_d, cos_d = self.calculate_day_circularity(date_val)

    temp = float(row.get("temperatuur", 15.0) or 15.0)
    wind_bft = float(row.get("windkracht", 2.0) or 2.0)
    clouds = float(row.get("bewolking", 4.0) or 4.0)
    precip = float(row.get("neerslag", 0.0) or 0.0)
    pressure = float(row.get("hpa", 1013.0) or 1013.0)

    return [
        sin_d,
        cos_d,
        temp / 35.0,
        wind_bft / 12.0,
        clouds / 8.0,
        precip / 10.0,
        pressure / 1050.0,
        0.5,
        0.5,
        0.3,
        0.7,
        0.2,
    ]

  def process_observations(self, df_excel, telpost_id="Onbekend", jaartal="Onbekend"):
    """Verwerkt een dataframe met waarnemingen en retourneert de resultaten."""
    results = []
    for _, row in df_excel.iterrows():
      species = row.get("speciesname", "Onbekend")

      features = self.build_feature_vector(row)
      neural_score = self.lne.predict(features)
      phenology_score = 0.88

      wind_bft = float(row.get("windkracht", 2) or 2)
      precip = float(row.get("neerslag", 0) or 0)
      guild_multiplier = self.apply_guild_multiplier(species, wind_bft, precip)

      final_score = neural_score * phenology_score * guild_multiplier

      results.append({
          "Telpost ID": str(telpost_id),
          "Jaar": str(jaartal),
          "Soort": str(species),
          "Neural Score (LNE)": round(neural_score, 3),
          "Phenology": round(phenology_score, 2),
          "Guild Mult": round(guild_multiplier, 2),
          "Final BSI Score": round(final_score, 3),
      })

    df_results = pd.DataFrame(results)
    if not df_results.empty:
      df_results = df_results.sort_values(by="Final BSI Score", ascending=False)
    return df_results


def run_biostat_model(df_excel):
  engine = BSIModelEngine()
  df_preds = engine.process_observations(df_excel)
  st.subheader("🧬 BSI - Model Pipeline Resultaat")
  st.dataframe(df_preds.head(15), use_container_width=True)