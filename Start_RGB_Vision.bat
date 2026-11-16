@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Python environment .venv was not found. See README.md for initial installation. No packages were installed automatically.', 'GS75 RGB Vision')"
  exit /b 2
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0tools\rgb_vision.py"
exit /b 0
