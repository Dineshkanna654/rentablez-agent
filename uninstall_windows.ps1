# uninstall_windows.ps1 — removes the Rentablez agent but preserves
# baseline.json so reinstalling on the same laptop keeps its original
# baseline.
#requires -RunAsAdministrator
$ErrorActionPreference = "Continue"

$nssm = "C:\Rentablez\nssm.exe"

Write-Host "==> Stopping service"
if (Test-Path $nssm) {
    & $nssm stop RentablezAgent 2>$null
    & $nssm remove RentablezAgent confirm 2>$null
} else {
    Stop-Service -Name RentablezAgent -Force -ErrorAction SilentlyContinue
    sc.exe delete RentablezAgent 2>$null
}

Write-Host "==> Removing files (preserving baseline.json)"
Remove-Item -Recurse -Force "C:\Rentablez" -ErrorAction SilentlyContinue
Get-ChildItem "C:\ProgramData\Rentablez" -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne "baseline.json" } |
    Remove-Item -Force -Recurse -ErrorAction SilentlyContinue

Write-Host "==> Uninstall complete."
Write-Host "    Baseline preserved at C:\ProgramData\Rentablez\baseline.json"
Write-Host "    To fully wipe, run: Remove-Item -Recurse -Force C:\ProgramData\Rentablez"
