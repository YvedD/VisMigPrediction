import subprocess
import sys


def run_streamlit():
    subprocess.run([sys.executable, "-m", "streamlit", "run", "main.py"], check=True)


if __name__ == "__main__":
    print("[*] Start VisMigPrediction Platform...")
    run_streamlit()