"""
bsi/image_manager.py
Beheert de vogelfoto cache in de SQLite tabel 'species_images' en Wikipedia REST API downloads.
"""

import sqlite3
import requests
import io
import time
import base64
from typing import Optional
from urllib.parse import quote


class SpeciesImageManager:
    REST_API_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
    SEARCH_API_URL = "https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=1&srsearch="
    USER_AGENT = "VoiceTally/5.0 (yves@voicetally.be)"

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """
        Zorgt ervoor dat de species_images tabel bestaat in SQLite[cite: 5].
        """
        create_sql = """
            CREATE TABLE IF NOT EXISTS species_images (
                latinName TEXT PRIMARY KEY NOT NULL,
                thumbnailBlob BLOB NOT NULL,
                lastUpdated INTEGER NOT NULL
            );
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(create_sql)
        except Exception as e:
            print(f"[ImageManager] Fout bij aanmaken species_images tabel: {e}")

    @staticmethod
    def clean_latin_name(latin_name: str) -> str:
        """
        Schoont de Latijnse naam op (bijv. "Buteo buteo / spec." -> "Buteo_buteo")[cite: 5].
        """
        if not latin_name:
            return ""
        clean = latin_name.split("/")[0].split("spec.")[0].strip()
        return clean.replace(" ", "_")

    def get_species_image_bytes(self, latin_name: str) -> Optional[bytes]:
        """
        Haalt de JPEG-bytes van de vogel op uit SQLite.
        Indien niet gecached, downloadt deze de foto van Wikipedia en slaat op in SQLite[cite: 5].
        """
        clean_latin = self.clean_latin_name(latin_name)
        if not clean_latin:
            return None

        # 1. Stap 1: Check SQLite Cache[cite: 5]
        cached_blob = self._get_from_db(clean_latin)
        if cached_blob:
            return cached_blob

        # 2. Stap 2: Download via Wikipedia REST API[cite: 5]
        image_bytes = self._fetch_from_wikipedia_rest(clean_latin)

        # 3. Stap 3: Fallback via Wikipedia Search API[cite: 5]
        if not image_bytes:
            search_title = self._fetch_title_from_search(clean_latin)
            if search_title:
                image_bytes = self._fetch_from_wikipedia_rest(search_title.replace(" ", "_"))

        # 4. Stap 4: Opslaan in SQLite cache[cite: 5]
        if image_bytes:
            self._save_to_db(clean_latin, image_bytes)

        return image_bytes

    def get_species_image_base64(self, latin_name: str) -> Optional[str]:
        """
        Levert de vogelfoto op als een Base64 data-URI string (geschikt voor Streamlit/HTML <img> tags)[cite: 5].
        """
        img_bytes = self.get_species_image_bytes(latin_name)
        if not img_bytes:
            return None
        b64 = base64.b64encode(img_bytes).decode('utf-8')
        return f"data:image/jpeg;base64,{b64}"

    def _get_from_db(self, clean_latin: str) -> Optional[bytes]:
        query = "SELECT thumbnailBlob FROM species_images WHERE latinName = ?"
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                row = cursor.execute(query, (clean_latin,)).fetchone()
                if row and row[0]:
                    return row[0]
        except Exception as e:
            print(f"[ImageManager] DB Read Fout for {clean_latin}: {e}")
        return None

    def _save_to_db(self, clean_latin: str, image_bytes: bytes):
        query = "INSERT OR REPLACE INTO species_images (latinName, thumbnailBlob, lastUpdated) VALUES (?, ?, ?)"
        now_ms = int(time.time() * 1000)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(query, (clean_latin, image_bytes, now_ms))
                conn.commit()
            print(f"[ImageManager] Foto succesvol gecached in SQLite voor {clean_latin}[cite: 5]")
        except Exception as e:
            print(f"[ImageManager] DB Write Fout for {clean_latin}: {e}")

    def _fetch_from_wikipedia_rest(self, title: str) -> Optional[bytes]:
        url = self.REST_API_URL + quote(title)
        headers = {"User-Agent": self.USER_AGENT}
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code != 200:
                return None
            data = resp.json()
            thumb_url = data.get("thumbnail", {}).get("source")
            if not thumb_url:
                return None

            img_resp = requests.get(thumb_url, headers=headers, timeout=8)
            if img_resp.status_code == 200:
                return img_resp.content
        except Exception as e:
            print(f"[ImageManager] Wikipedia REST Fout for {title}: {e}")
        return None

    def _fetch_title_from_search(self, query: str) -> Optional[str]:
        url = self.SEARCH_API_URL + quote(query)
        headers = {"User-Agent": self.USER_AGENT}
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code != 200:
                return None
            data = resp.json()
            results = data.get("query", {}).get("search", [])
            if results:
                return results[0].get("title")
        except Exception as e:
            print(f"[ImageManager] Wikipedia Search Fout for {query}: {e}")
        return None