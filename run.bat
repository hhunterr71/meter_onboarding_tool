@echo off
echo Activating virtual environment and running Meter Onboard Tool...

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Run the main script
python meter_onboard.py

pause