@echo off
REM Double-click to start the fxlab dashboard. Close this window to stop it.
cd /d "%~dp0"
echo Starting fxlab dashboard at http://127.0.0.1:8501 ...
REM open the browser a few seconds later, once the server is up
start "" /min cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8501"
".venv\Scripts\streamlit.exe" run streamlit_app.py --server.port 8501
