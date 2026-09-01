import json
import os
import streamlit as st


def load_species():
  """Laadt species.json uit de serverdata map[cite: 4, 11]."""
  path = os.path.join("serverdata", "species.json")
  if os.path.exists(path):
    with open(path, "r", encoding="utf-8") as f:
      data = json.load(f)
      return data.get("json", data) if isinstance(data, dict) else data
  return []


def load_telpost_locations():
  """Laadt telpost_locaties.json uit de serverdata map[cite: 3, 11]."""
  path = os.path.join("serverdata", "telpost_locaties.json")
  if os.path.exists(path):
    with open(path, "r", encoding="utf-8") as f:
      data = json.load(f)
      return data.get("json", data) if isinstance(data, dict) else data
  return []


def load_sites():
  """Laadt sites.json uit de serverdata map[cite: 5, 11]."""
  path = os.path.join("serverdata", "sites.json")
  if os.path.exists(path):
    with open(path, "r", encoding="utf-8") as f:
      data = json.load(f)
      return data.get("json", data) if isinstance(data, dict) else data
  return []


def load_neural_engine():
  """Laadt neural_engine.json uit de AI-models map."""
  path = os.path.join("AI-models", "neural_engine.json")
  if os.path.exists(path):
    with open(path, "r", encoding="utf-8") as f:
      return json.load(f)
  return {}