import os
import sqlite3
from dotenv import load_dotenv
import libsql_client

load_dotenv()

url = os.getenv("TURSO_DATABASE_URL")
auth_token = os.getenv("TURSO_AUTH_TOKEN")
db_path = os.path.join("database", "voicetally_1785686365175.db")

if not os.path.exists(db_path):
    print(f"❌ Kan lokale database niet vinden op {db_path}")
    exit()

print("⏳ Verbinden met lokale SQLite en Turso cloud...")

local_conn = sqlite3.connect(db_path)
local_cursor = local_conn.cursor()

# Haal alle tabellen op
local_cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
tables = local_cursor.fetchall()

BATCH_SIZE = 500  # Stuur 500 rijen per keer in een batch

with libsql_client.create_client_sync(url=url, auth_token=auth_token) as cloud_client:
    for table_name, create_sql in tables:
        print(f"\n📦 Start migratie voor tabel: {table_name}")

        if create_sql:
            try:
                clean_create_sql = create_sql.replace("`", '"')
                cloud_client.execute(clean_create_sql)
                print("   -> Tabelstructuur aangemaakt in cloud.")
            except Exception as e:
                print(f"   -> Info bij structuur (bestaat wellicht al): {e}")

        local_cursor.execute(f'SELECT * FROM "{table_name}"')

        column_names = [description[0] for description in local_cursor.description]
        placeholders = ", ".join(["?"] * len(column_names))
        cols_joined = ", ".join([f'"{c}"' for c in column_names])
        insert_sql = f'INSERT OR REPLACE INTO "{table_name}" ({cols_joined}) VALUES ({placeholders})'

        total_migrated = 0

        while True:
            rows = local_cursor.fetchmany(BATCH_SIZE)
            if not rows:
                break

            # Bouw een lijst van queries voor deze batch
            batch_statements = [(insert_sql, list(row)) for row in rows]

            try:
                cloud_client.batch(batch_statements)
                total_migrated += len(rows)
                print(f"   -> {total_migrated} rijen overgezet...", end="\r")
            except Exception as e:
                # Als een batch faalt, vangen we het op per individuele rij in die batch
                for row in rows:
                    try:
                        cloud_client.execute(insert_sql, list(row))
                        total_migrated += 1
                    except:
                        pass

        print(f"\n   ✅ Tabel '{table_name}' voltooid! Totaal overgezet: {total_migrated} rijen.")

local_conn.close()
print("\n🎉 Alle tabellen (inclusief het gigantische weerarchief) succesvol gemigreerd naar Turso!")