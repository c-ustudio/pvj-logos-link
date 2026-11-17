# pvj-logos-link launcher for Windows. The .bat files call this.
#
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 [-Mode signals|pvj] [-Mock] [-Pvj 192.168.1.40]
#                                                      [-Peer <logos address>] [-Allow <addr,addr>] [-Confirm] [-Lan]
param(
  [ValidateSet('signals', 'pvj')][string]$Mode = 'signals',
  [switch]$Mock,
  [string]$Pvj = '',          # PVJ phone IP(s), comma-separated; asked for in pvj mode if empty
  [string]$Peer = '',         # another bridge's Logos address, to send PVJ state to
  [string]$Allow = '',        # Logos addresses allowed to control PVJ
  [switch]$Confirm,           # reply "ok: ..." to senders
  [switch]$Lan,               # serve the visual to other machines (http://<this-ip>:8765)
  [string]$Reply = ''
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$py = $null
foreach ($c in @('py', 'python', 'python3')) {
  if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break }
}
if (-not $py) {
  Write-Host "Python 3 is not installed. Install it with:" -ForegroundColor Yellow
  Write-Host "  winget install Python.Python.3.12"
  Write-Host "then open a new window and run this again."
  Read-Host "Press Enter to close"
  exit 1
}
$pyArgs = @()
if ($py -eq 'py') { $pyArgs += '-3' }

if (-not $Mock) {
  $ctl = Join-Path $env:LOCALAPPDATA 'logosctl\bin\logosctl.exe'
  if (-not (Get-Command logosctl -ErrorAction SilentlyContinue) -and -not (Test-Path $ctl)) {
    Write-Host "Installing logosctl from the official Logos script (no admin needed)..."
    Invoke-RestMethod https://raw.githubusercontent.com/logos-co/logos-docs/main/resources/scripts/install-logosctl.ps1 | Invoke-Expression
  }
}

if ($Mode -eq 'pvj' -and -not $Pvj) {
  $Pvj = Read-Host "PVJ phone IP (shown in PVJ's link panel; Enter to skip)"
}

$a = $pyArgs + @('bridge\logos_bridge.py', '--open', '--mode', $Mode)
if ($Mock)    { $a += '--mock' }
if ($Pvj)     { $a += @('--pvj', $Pvj) }
if ($Peer)    { $a += @('--peer', $Peer) }
if ($Allow)   { $a += @('--allow', $Allow) }
if ($Confirm) { $a += '--confirm' }
if ($Lan)     { $a += @('--host', '0.0.0.0') }
if ($Reply)   { $a += @('--reply', $Reply) }

Write-Host "Starting pvj-logos-link ($Mode). Close this window or press Ctrl+C to stop."
& $py @a
