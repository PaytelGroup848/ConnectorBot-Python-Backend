@echo off
echo ===================================================
echo  Starting Connector AI Platform Backend on Port 8001
echo  Swagger UI: http://localhost:8001/docs
echo ===================================================
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
pause

