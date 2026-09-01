import os
import libsql
from dotenv import load_dotenv

# Laad gegarandeerd de variabelen uit het .env bestand in de hoofdmap
load_dotenv()

db_url = os.getenv("TURSO_DATABASE_URL")
auth_token = os.getenv("TURSO_AUTH_TOKEN")

print("--- VERBINDINGSTEST ---")
print(f"Database URL in .env gevonden: {db_url is not None}")
print(f"Auth Token in .env gevonden: {auth_token is not None}")

if not db_url or not auth_token:
    print("\n❌ FOUT: De gegevens uit je .env bestand zijn niet geladen.")
    print("Controleer of het bestand exact '.env' heet en in de hoofdmap staat.")
else:
    try:
        print("\n⏳ Verbinding maken met Turso Cloud...")
        # Verbinding maken met de officiële libsql library
        conn = libsql.connect(database=db_url, auth_token=auth_token)
        cursor = conn.cursor()

        cursor.execute("SELECT 1;")
        resultaat = cursor.fetchone()

        print("\n✅ SUCCES! Je laptop is succesvol verbonden met je Turso cloud-database.")
        print(f"Antwoord van database (moet 1 zijn): {resultaat[0] if resultaat else None}")

        conn.close()
    except Exception as e:
        print(f"\n❌ FOUT: Kon geen verbinding maken met Turso. Melding: {e}")
