Cloudflared-tunnel voor bètatesters

Snelstart (Windows PowerShell):

1. Installeer cloudflared als het nog niet is geïnstalleerd:
   - https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation

2. Open PowerShell in de repository root (deze map bevat main.py).

3. Start de app met tunnel (standaardpoort 8501):
   .\start_with_tunnel.ps1

   Optioneel: andere poort gebruiken, bijvoorbeeld 8080:
   .\start_with_tunnel.ps1 -Port 8080

Wat het script doet:
- Controleert of cloudflared beschikbaar is.
- Start Streamlit (main.py) headless op de opgegeven poort.
- Start cloudflared ephemeral tunnel en leest de publieke URL uit de uitvoer.
- Toont de publieke URL en PID's. Druk op een toets om beide processen te stoppen.

Opmerkingen:
- Dit gebruikt een tijdelijke (ephemeral) tunnel die een trycloudflare- of cfargotunnel-domein oplevert.
- Voor persistente tunnels en eigen subdomeinen, configureer een cloudflared tunnel volgens Cloudflare-documentatie en gebruik je account/credentials.
- Zie cloudflared_output.log in de repo-map voor troubleshooting-logs.