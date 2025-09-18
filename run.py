#!/usr/bin/env python3
"""
Cross-platform run script for Meter Onboard Tool
Works on Windows, Linux, and macOS
"""

import os
import sys
import subprocess
import platform

def get_python_executable():
    """Get the appropriate Python executable"""
    system = platform.system().lower()
    if system == "windows":
        return os.path.join("venv", "Scripts", "python.exe")
    else:  # Linux, macOS, etc.
        return os.path.join("venv", "bin", "python")

def check_venv_exists():
    """Check if virtual environment exists"""
    venv_python = get_python_executable()
    return os.path.exists(venv_python)

def main():
    print("Starting Meter Onboard Tool...")
    
    # Check if virtual environment exists
    if not check_venv_exists():
        print("Virtual environment not found. Please run setup first:")
        print("  python setup.py")
        sys.exit(1)
    
    # Get the Python executable in the virtual environment
    venv_python = get_python_executable()
    
    # Run the meter onboard tool
    try:
        subprocess.run([venv_python, "meter_onboard.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running meter onboard tool: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)

if __name__ == "__main__":
    main()