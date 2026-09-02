"""
bsi/species_resolver.py
Vertaalt Soort-ID's naar Nederlandse en Latijnse namen, en koppelt neurale output-neuronen.
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Any


@dataclass
class SpeciesItem:
    soortid: str
    soortnaam: str
    latin: str
    soortkey: str = ""
    sortering: str = ""


class SpeciesResolver:
    def __init__(self, base_dir: Path = Path(".")):
        self.base_dir = Path(base_dir)
        self.species_by_id: Dict[str, SpeciesItem] = {}
        self.species_by_canonical: Dict[str, str] = {}
        self.model_labels: Optional[List[str]] = None

        self._load_species_json()
        self._load_model_labels()

    @staticmethod
    def normalize_canonical(input_str: str) -> str:
        s = input_str.lower().strip()
        s = re.sub(r'[àáâãäå]', 'a', s)
        s = re.sub(r'[èéêë]', 'e', s)
        s = re.sub(r'[ìíîï]', 'i', s)
        s = re.sub(r'[òóôõö]', 'o', s)
        s = re.sub(r'[ùúûü]', 'u', s)
        return s

    def _load_species_json(self):
        # Controleer meerdere mogelijke locaties voor maximale robuustheid
        possible_paths = [
            self.base_dir / "serverdata" / "species.json",
            Path("serverdata") / "species.json",
            Path("C:/Eigen bestanden Yves/Programeren/Python/VisMigPrediction/serverdata/species.json"),
            self.base_dir / "VT5" / "serverdata" / "species.json"
        ]

        filepath = None
        for p in possible_paths:
            if p.exists():
                filepath = p
                break

        if not filepath:
            print(f"[SpeciesResolver] WAARSCHUWING: species.json kon nergens worden gevonden.")
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_list = data.get("json", []) if isinstance(data, dict) else data
            for item in raw_list:
                sid = str(item.get("soortid", "")).strip()
                snaam = str(item.get("soortnaam", "")).strip()
                slatin = str(item.get("latin", "")).strip()
                skey = str(item.get("soortkey", snaam)).strip()
                sort = str(item.get("sortering", sid)).strip()

                if sid:
                    sp = SpeciesItem(soortid=sid, soortnaam=snaam, latin=slatin, soortkey=skey, sortering=sort)
                    self.species_by_id[sid] = sp
                    if snaam:
                        self.species_by_canonical[self.normalize_canonical(snaam)] = sid
                    if slatin:
                        self.species_by_canonical[self.normalize_canonical(slatin)] = sid

            print(f"[SpeciesResolver] Succesvol {len(self.species_by_id)} soorten geladen uit {filepath}")
        except Exception as e:
            print(f"[SpeciesResolver] Fout bij laden species.json: {e}")

    def _load_model_labels(self):
        possible_paths = [
            self.base_dir / "AI-models" / "models" / "model_labels.json",
            Path("AI-models") / "models" / "model_labels.json",
            Path("C:/Eigen bestanden Yves/Programeren/Python/VisMigPrediction/AI-models/models/model_labels.json"),
            self.base_dir / "VT5" / "AI-models" / "models" / "model_labels.json"
        ]

        filepath = None
        for p in possible_paths:
            if p.exists():
                filepath = p
                break

        if filepath:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    self.model_labels = json.load(f)
                print(f"[SpeciesResolver] {len(self.model_labels)} neuraal netwerk labels geladen uit {filepath}.")
            except Exception as e:
                print(f"[SpeciesResolver] Fout bij laden model_labels.json: {e}")

    def get_name(self, soort_id: str) -> str:
        sp = self.species_by_id.get(str(soort_id))
        return sp.soortnaam if sp else f"Onbekend ({soort_id})"

    def get_latin(self, soort_id: str) -> str:
        sp = self.species_by_id.get(str(soort_id))
        return sp.latin if sp else ""

    def get_species_item(self, soort_id: str) -> Optional[SpeciesItem]:
        return self.species_by_id.get(str(soort_id))

    def resolve_id(self, name_query: str) -> Optional[str]:
        norm = self.normalize_canonical(name_query)
        return self.species_by_canonical.get(norm)

    def map_neuron_index_to_species(self, neuron_index: int) -> Optional[SpeciesItem]:
        if not self.model_labels or neuron_index < 0 or neuron_index >= len(self.model_labels):
            return None
        soort_id = self.model_labels[neuron_index]
        return self.get_species_item(soort_id)