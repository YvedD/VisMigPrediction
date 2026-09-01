import os
import sqlite3

# Pad naar je lokale database
db_path = os.path.join("database", "voicetally_1785686365175.db")
dump_path = "backup_dump.sql"

print("⏳ Bezig met genereren van de SQL-dump via Python...")

# Open de lokale database
conn = sqlite3.connect(db_path)

# Schrijf alle SQL-statements weg naar een bestand
with open(dump_path, "w", encoding="utf-8") as f:
  for line in conn.iterdump():
    f.write(f"{line}\n")

conn.close()
print(f"✅ Succes! Je SQL-dump is opgeslagen als '{dump_path}' in je projectmap.")