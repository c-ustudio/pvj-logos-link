@echo off
rem Fake PVJ commands sent to a phone (or tools\fake_pvj.py), no Logos needed.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" -Mode pvj -Mock
