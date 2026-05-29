# setup_windows.ps1 — one-shot installer for the Rentablez agent on Windows.
# Run as Administrator from an elevated PowerShell prompt.
#requires -RunAsAdministrator
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Python {
    try {
        $version = (& python --version 2>&1) -replace 'Python ', ''
        $parts = $version.Split('.')
        return ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10)
    } catch {
        return $false
    }
}

if (-not (Test-Python)) {
    Write-Host "==> Python 3.10+ not found; installing via winget."
    winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
    if (-not (Test-Python)) {
        Write-Error "Python install failed. Aborting."
        exit 1
    }
}

$PythonPath = (Get-Command python).Source

$Token = ""
while ($Token -notmatch '^RTBZ-LAP-\d{5,}$') {
    $Token = Read-Host "Enter device token (e.g. RTBZ-LAP-00042)"
    if ($Token -notmatch '^RTBZ-LAP-\d{5,}$') {
        Write-Host "  Invalid format. Must look like RTBZ-LAP-<5+ digits>."
    }
}

$Endpoint = if ($env:RENTABLEZ_ENDPOINT) { $env:RENTABLEZ_ENDPOINT } else { "https://api.rentablez.com/devices/checkin" }

Write-Host "==> Creating directories"
New-Item -ItemType Directory -Force -Path "C:\Rentablez" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\ProgramData\Rentablez" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\ProgramData\Rentablez\logs" | Out-Null

$acl = Get-Acl "C:\ProgramData\Rentablez"
$acl.SetAccessRuleProtection($true, $false)
$acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) | Out-Null }
$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
    "NT AUTHORITY\SYSTEM", "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))
$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
    "BUILTIN\Administrators", "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))
Set-Acl "C:\ProgramData\Rentablez" $acl

if (-not (Test-Path "$ScriptDir\vendor\nssm.exe")) {
    Write-Error "vendor\nssm.exe is missing. Download nssm 2.24 from https://nssm.cc/release/nssm-2.24.zip, extract win64\nssm.exe to the vendor\ directory, and re-run."
    exit 1
}

Write-Host "==> Copying agent files"
if (Test-Path "C:\Rentablez\rentablez") { Remove-Item -Recurse -Force "C:\Rentablez\rentablez" }
Copy-Item -Recurse -Force "$ScriptDir\rentablez" "C:\Rentablez\"
Copy-Item -Force "$ScriptDir\rentablez_agent.py" "C:\Rentablez\"
Copy-Item -Force "$ScriptDir\vendor\nssm.exe" "C:\Rentablez\"

Write-Host "==> Writing config"
$cfg = [ordered]@{
    device_token = $Token
    endpoint = $Endpoint
    installed_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}
$cfg | ConvertTo-Json | Set-Content -Path "C:\ProgramData\Rentablez\config.json" -Encoding UTF8

Write-Host "==> Registering service via nssm"
$nssm = "C:\Rentablez\nssm.exe"
try { & $nssm stop RentablezAgent } catch {}
try { & $nssm remove RentablezAgent confirm } catch {}

& $nssm install RentablezAgent $PythonPath "C:\Rentablez\rentablez_agent.py"
& $nssm set RentablezAgent Start SERVICE_AUTO_START
& $nssm set RentablezAgent ObjectName LocalSystem
& $nssm set RentablezAgent DisplayName "system-service"
& $nssm set RentablezAgent Description "System service."
& $nssm set RentablezAgent AppDirectory "C:\Rentablez"
& $nssm set RentablezAgent AppEnvironmentExtra "PYTHONPATH=C:\Rentablez"
& $nssm set RentablezAgent AppExit Default Exit
& $nssm set RentablezAgent AppStdout "C:\ProgramData\Rentablez\logs\nssm-stdout.log"
& $nssm set RentablezAgent AppStderr "C:\ProgramData\Rentablez\logs\nssm-stderr.log"

Write-Host "==> Starting service (first run captures baseline)"
& $nssm start RentablezAgent

Write-Host ""
Write-Host "===================================="
Write-Host "  Rentablez agent installed."
Write-Host "  Device token: $Token"
Write-Host "  Endpoint:     $Endpoint"
Write-Host "  Log file:     C:\ProgramData\Rentablez\logs\agent.log"
Write-Host "===================================="
