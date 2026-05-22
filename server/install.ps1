# ParkWatch Server — Windows Install Script (PowerShell)
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  ParkWatch Server Installer (Windows)"      -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
try {
    $pyVersion = python --version 2>&1
    Write-Host "[OK] $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python not found. Please install Python 3.9+ from https://python.org" -ForegroundColor Red
    exit 1
}

# Create virtual environment
if (-Not (Test-Path "venv")) {
    Write-Host "[*] Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
} else {
    Write-Host "[OK] Virtual environment already exists." -ForegroundColor Green
}

# Activate and install
Write-Host "[*] Installing Python dependencies..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"
pip install --upgrade pip
pip install -r requirements.txt

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Installation complete!"                      -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  To run the server:" -ForegroundColor White
Write-Host ""
Write-Host "    .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host "    python app.py" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Server will start on http://0.0.0.0:2026" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Cyan
