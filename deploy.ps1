param(
    [string]$Message = "Deploy update"
)

$ErrorActionPreference = "Stop"

$Repo = "C:\Eigen bestanden Yves\Programeren\Python\VisMigPrediction"
$Key = "C:\Users\ydsds\Downloads\ssh-key-2026-09-13.key"
$HostName = "ubuntu@144.21.35.64"
$RemotePath = "/home/ubuntu/vismigprediction"

Set-Location $Repo

git add -A

$staged = git diff --cached --name-only
if ($staged) {
    git commit -m $Message
}

git push

ssh -i $Key $HostName "cd $RemotePath && ./deploy_remote.sh"
