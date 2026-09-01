import os
import sqlite3

# Pad naar je database
db_path = os.path.join("database", "voicetally_1785686365175.db")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Vraag de kolommen en de eerste 5 rijen op uit 'waarnemingen'
cursor.execute("SELECT * FROM waarnemingen LIMIT 5;")
rows = cursor.fetchall()

# Haal de kolomnamen op zodat we weten wat wat is
column_names = [description[0] for description in cursor.description]

print("📋 Kolommen in 'waarnemingen':")
print(column_names)
print("\n🔍 Eerste 5 rijen:")

for i, row in enumerate(rows, 1):
  print(f"\nRij {i}: {row}")

conn.close()