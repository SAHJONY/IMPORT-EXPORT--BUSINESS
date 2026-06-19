@echo off
rem ---- start FastAPI and ngrok with auto‑restart ----
set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"
:loop
    echo Starting FastAPI server on port 51111...
    start "FastAPI" cmd /c "uvicorn fastapi_server:app --host 0.0.0.0 --port 51111"
    timeout /t 5 >nul
    echo Starting ngrok tunnel (my_fastapi_50001)...
    start "ngrok" cmd /c "ngrok start --config=ngrok.yml my_fastapi_50001"
    rem Wait for either process to exit then restart both
    timeout /t 30 >nul
    rem Simple check – if any process died, kill both and loop
    tasklist /fi "imagename eq python.exe" | findstr /i fastapi_server.py >nul || (
        echo FastAPI stopped – restarting both services.
        taskkill /im python.exe /f >nul 2>&1
        taskkill /im ngrok.exe /f >nul 2>&1
        goto loop
    )
    tasklist /fi "imagename eq ngrok.exe" | findstr /i my_fastapi_50001 >nul || (
        echo ngrok stopped – restarting both services.
        taskkill /im python.exe /f >nul 2>&1
        taskkill /im ngrok.exe /f >nul 2>&1
        goto loop
    )
    rem Sleep before next health check
    timeout /t 60 >nul
    goto loop
