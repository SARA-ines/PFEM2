@echo off
title Lancement PFEM2 - Support Client BIG

echo ============================================
echo   PFEM2 - Plateforme Support Client BIG
echo ============================================
echo.

:: ── Backend ──────────────────────────────────
echo [1/2] Lancement du Backend (port 8000)...
start "BACKEND - FastAPI" cmd /k "cd /d %~dp0backend && .venv\Scripts\activate && uvicorn main:app --host 127.0.0.1 --port 8000 --reload"

timeout /t 3 /nobreak >nul

:: ── Frontend ─────────────────────────────────
echo [2/2] Lancement du Frontend (port 5173)...
start "FRONTEND - React" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 4 /nobreak >nul

:: ── Ouvrir le navigateur ─────────────────────
echo.
echo Ouverture du navigateur...
start http://127.0.0.1:5173

echo.
echo ============================================
echo   Application disponible sur :
echo   http://127.0.0.1:5173
echo ============================================
echo.
pause