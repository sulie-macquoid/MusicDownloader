$ErrorActionPreference = "Stop"

# Update these before public use:
$Owner = "<OWNER>"
$Repo = "<REPO>"
$Tag = "v1.0.0"
$Asset = "sullys-music-downloader-windows.exe"

$DownloadUrl = "https://github.com/$Owner/$Repo/releases/download/$Tag/$Asset"
$InstallDir = Join-Path $env:LOCALAPPDATA "sullys-music-downloader"
$ExePath = Join-Path $InstallDir "sully's music downloader.exe"
$ShortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "sully's music downloader.lnk"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Write-Host "Downloading $DownloadUrl"
Invoke-WebRequest -Uri $DownloadUrl -OutFile $ExePath

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExePath
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Save()

Write-Host "Installed to $ExePath"
Write-Host "Desktop shortcut created: $ShortcutPath"
