@echo off
powershell -NoProfile -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/<OWNER>/<REPO>/main/scripts/install-windows.ps1 -UseBasicParsing | iex"
