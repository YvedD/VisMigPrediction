param(
    [string]$Message = "Deploy update"
)

$ErrorActionPreference = "Stop"

$Repo = "C:\Eigen bestanden Yves\Programeren\Python\VisMigPrediction"
$Key = "C:\Users\ydsds\Downloads\ssh-key-2026-09-13.key"
$HostName = "ubuntu@144.21.35.64"
$RemotePath = "/home/ubuntu/vismigprediction"

Set-Location $Repo

# Always stage everything for deploy.
git add -A

# Commit only if the index changed.
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m $Message
}

# Push the branch that is currently checked out.
git push origin HEAD

# Trigger deploy on the remote OCI VM.
ssh -i $Key $HostName "cd $RemotePath && bash ./deploy_remote.sh"
