import sqlite3
import json
from pathlib import Path


def generate_sites_dna(db_path: str, output_json_path: str = "sites_DNA.json"):
    path = Path(output_json_path)
    if path.exists():
        return

    query = """
            SELECT h.telpostid, \
                   w.soortid, \
                   SUM(CAST(w.aantal AS INTEGER) + CAST(w.aantalterug AS INTEGER) + CAST(w.aantal_plus AS INTEGER) + \
                       CAST(w.aantalterug_plus AS INTEGER)) as total_count
            FROM waarnemingen w
                     INNER JOIN telling_headers h ON w.tellingid = h.tellingid
            WHERE h.telpostid IS NOT NULL \
              AND h.telpostid != ''
            GROUP BY h.telpostid, w.soortid \
            """

    dna_data = {}
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            rows = cursor.execute(query).fetchall()

            for row in rows:
                site_id = str(row["telpostid"])
                species_id = str(row["soortid"])
                count = int(row["total_count"])

                if site_id not in dna_data:
                    dna_data[site_id] = {
                        "total_specimens": 0,
                        "species_counts": {}
                    }

                dna_data[site_id]["species_counts"][species_id] = count
                dna_data[site_id]["total_specimens"] += count

        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(dna_data, f, ensure_ascii=False, indent=4)

    except Exception as e:
        print(f"[X] Fout bij genereren sites_DNA: {e}")