#!/usr/bin/env python3
"""
Cross-platform setup script for Meter Onboard Tool
Works on Windows, Linux, and macOS
"""

import os
import sys
import subprocess
import platform

def run_command(command, shell=False):
    """Run a command and handle errors"""
    try:
        result = subprocess.run(command, shell=shell, check=True, capture_output=True, text=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(command) if isinstance(command, list) else command}")
        print(f"Error: {e.stderr}")
        return False

def get_venv_activate_script():
    """Get the appropriate activation script based on OS"""
    system = platform.system().lower()
    if system == "windows":
        return os.path.join("venv", "Scripts", "activate")
    else:  # Linux, macOS, etc.
        return os.path.join("venv", "bin", "activate")

def get_python_executable():
    """Get the appropriate Python executable"""
    system = platform.system().lower()
    if system == "windows":
        return os.path.join("venv", "Scripts", "python.exe")
    else:  # Linux, macOS, etc.
        return os.path.join("venv", "bin", "python")

def main():
    print("Setting up Meter Onboard Tool virtual environment...")
    print(f"Detected OS: {platform.system()}")
    
    # Check if Python is available
    try:
        subprocess.run([sys.executable, "--version"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print("Error: Python not found. Please install Python 3.6 or higher.")
        sys.exit(1)
    
    # Create virtual environment
    print("Creating virtual environment...")
    if not run_command([sys.executable, "-m", "venv", "venv"]):
        print("Failed to create virtual environment.")
        sys.exit(1)
    
    # Get the Python executable in the virtual environment
    venv_python = get_python_executable()
    
    # Install dependencies
    print("Installing dependencies...")
    if not run_command([venv_python, "-m", "pip", "install", "-r", "requirements.txt"]):
        print("Failed to install dependencies.")
        sys.exit(1)
    
    print("\nVirtual environment setup complete!")
    print("\nTo run the tool:")
    print("  python run.py")
    print("\nOr manually activate the environment:")
    
    system = platform.system().lower()
    if system == "windows":
        print("  venv\\Scripts\\activate")
    else:
        print("  source venv/bin/activate")
    
    print("  python meter_onboard.py")

if __name__ == "__main__":
    main()