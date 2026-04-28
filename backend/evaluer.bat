@echo off
cd /d %~dp0
call .venv\Scripts\activate
python evaluate_realistic.py
pause