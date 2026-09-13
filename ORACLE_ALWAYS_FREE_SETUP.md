# Oracle Always Free setup

## 1. Maak de VM aan
- Kies **Ubuntu 22.04 LTS**
- Kies **VM.Standard.A1.Flex**
- Voeg je **public SSH key** toe
- Open inbound poorten **22**, **80**, **443**

## 2. Log in via SSH
Gebruik je bestaande private key uit Downloads in PyCharm of via SSH.

## 3. Installeer systeemvereisten
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx
```

## 4. Deploy de code
Kopieer de hele repo naar bijvoorbeeld:
```bash
/home/ubuntu/vismigprediction
```

Zorg dat deze mappen mee gaan:
- `database/`
- `serverdata/`
- `AI-models/`
- `BSI_logo.png`
- `sites_DNA.json`

## 5. Python omgeving
```bash
cd /home/ubuntu/vismigprediction
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 6. Test de app
```bash
streamlit run main.py
```

De app luistert lokaal op `127.0.0.1:8501`.

## 7. Nginx reverse proxy
Maak bijvoorbeeld `/etc/nginx/sites-available/vismigprediction`:
```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Activeer:
```bash
sudo ln -s /etc/nginx/sites-available/vismigprediction /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## 8. systemd service
Maak `/etc/systemd/system/vismigprediction.service`:
```ini
[Unit]
Description=VisMigPrediction Streamlit App
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/vismigprediction
Environment="PATH=/home/ubuntu/vismigprediction/.venv/bin"
ExecStart=/home/ubuntu/vismigprediction/.venv/bin/streamlit run main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Activeer:
```bash
sudo systemctl daemon-reload
sudo systemctl enable vismigprediction
sudo systemctl start vismigprediction
sudo systemctl status vismigprediction
```
