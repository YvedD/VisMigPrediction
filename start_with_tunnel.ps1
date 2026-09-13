param(
    [int]$Port = 8501
)

# Controleer of cloudflared beschikbaar is
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "cloudflared is niet gevonden in PATH. Download en installeer van: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation"
    Exit 2
}

# Start Streamlit (headless) in achtergrond
Write-Host "Starten Streamlit op poort $Port..."
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$mainPath = Join-Path $scriptDir "main.py"
$streamlitArgs = "-m streamlit run `"$mainPath`" --server.port $Port --server.headless true"
$streamlitProc = Start-Process -FilePath "python" -ArgumentList $streamlitArgs -WindowStyle Hidden -PassThru

Start-Sleep -Seconds 3

# Controleer of Streamlit gestart is (optioneel)
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
} catch {
    # ignore
}

Write-Host "Starten cloudflared tunnel naar http://localhost:$Port..."
$logFile = Join-Path $scriptDir "cloudflared_output.log"
if (Test-Path $logFile) { Remove-Item $logFile -Force }

# Start cloudflared en redirect output naar log
$cfArgs = "tunnel --url http://localhost:$Port --loglevel info"
$cfProc = Start-Process -FilePath "cloudflared" -ArgumentList $cfArgs -RedirectStandardOutput $logFile -RedirectStandardError $logFile -PassThru

Write-Host "Wachten op publieke URL in cloudflared output (max 30s)..."
$max = 30
$i = 0
$url = $null
while ($i -lt $max -and -not $url) {
    Start-Sleep -Seconds 1
    if (Test-Path $logFile) {
        $content = Get-Content $logFile -Raw -ErrorAction SilentlyContinue
        if ($content) {
            $m = [regex]::Match($content, '(https?://[^\s]+?(?:trycloudflare\.com|cfargotunnel\.com|trycloudflare\.dev)?)')
            if ($m.Success) { $url = $m.Groups[1].Value; break }
            $m2 = [regex]::Match($content, '(https?://[^\s]+)')
            if ($m2.Success) { $candidate = $m2.Groups[1].Value; if ($candidate -like 'https://*') { $url = $candidate; break } }
        }
    }
    $i++
}

if ($url) {
    Write-Host "Tunnel actief: $url"
    Write-Host "Streamlit PID: $($streamlitProc.Id) | cloudflared PID: $($cfProc.Id)"
    Write-Host "Logbestand: $logFile"
    Write-Host "Druk op een toets om tunnel en Streamlit te stoppen..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    Write-Host "Beëindigen processen..."
    try { Stop-Process -Id $cfProc.Id -ErrorAction SilentlyContinue } catch {}
    try { Stop-Process -Id $streamlitProc.Id -ErrorAction SilentlyContinue } catch {}
    Write-Host "Gestopt."
    Exit 0
} else {
    Write-Host "Kon publieke URL niet vinden in cloudflared output. Bekijk $logFile voor details." -ForegroundColor Red
    Write-Host "Streamlit PID: $($streamlitProc.Id) | cloudflared PID: $($cfProc.Id)"
    Write-Host "Je kunt de tunnel ook handmatig starten met: cloudflared tunnel --url http://localhost:$Port"
    Exit 3
}