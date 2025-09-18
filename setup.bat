@echo off
echo Setting up Meter Onboard Tool virtual environment...

REM Create virtual environment
python -m venv venv

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install dependencies
pip install -r requirements.txt

echo.
echo Virtual environment setup complete!
echo To activate the environment in the future, run: venv\Scripts\activate.bat
echo To run the tool: python main_script.py
pause