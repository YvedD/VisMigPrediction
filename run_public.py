import subprocess
import sys
import time
import re
import threading
from pathlib import Path


def run_streamlit():
    subprocess.run([sys.executable, "-m", "streamlit", "run", "main.py"], check=True)


def run_cloudflare():
    # Gebruik direct de cloudflared.exe die nu in de projectmap staat
    cmd = "cloudflared.exe tunnel --url http://localhost:8501"

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
        shell=True
    )

    url_found = False
    url_file = Path("active_tunnel_url.txt")

    for line in process.stdout:
        print(line, end="")
        if "trycloudflare.com" in line and not url_found:
            match = re.search(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", line)
            if match:
                public_url = match.group(0)
                url_found = True
                url_file.write_text(public_url, encoding="utf-8")
                print("\n" + "=" * 70)
                print(f" 🚀 JOUW PUBLIEKE LINK IS LIVE: {public_url}")
                print("=" * 70 + "\n")

                try:
                    import pyperclip
                    pyperclip.copy(public_url)
                    print(" (Gekopieerd naar je klembord!)")
                except ImportError:
                    pass

    process.wait()


if __name__ == "__main__":
    print("[*] Start VisMigPrediction Platform + Cloudflare Tunnel...")
    cf_thread = threading.Thread(target=run_cloudflare, daemon=True)
    cf_thread.start()
    time.sleep(3)
    try:
        run_streamlit()
    except KeyboardInterrupt:
        print("\n[*] Applicatie gestopt.")
        url_file = Path("active_tunnel_url.txt")
        if url_file.exists():
            url_file.unlink()