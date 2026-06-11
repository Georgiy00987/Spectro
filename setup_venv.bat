@echo off
echo ============================================================
echo  Spectro - virtual environment setup
echo ============================================================
echo.

py -3.11 -m venv .venv
if errorlevel 1 (
    echo ERROR: Python 3.11 not found. Download from https://python.org
    pause & exit /b 1
)

call .venv\Scripts\activate.bat

echo Installing main dependencies...
pip install -r requirements.txt

echo.
echo ============================================================
echo  Choose torch variant for your hardware:
echo.
echo  CPU (any PC):
echo    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
echo.
echo  NVIDIA CUDA 11.8:
echo    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
echo.
echo  NVIDIA CUDA 12.1:
echo    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
echo ============================================================
echo.

echo Installing scrcpy-client from GitHub...
pip install git+https://github.com/leng-yue/py-scrcpy-client.git@f5ddaef4aa471d93f9af5f7559023f0b6a531ec9

echo.
echo ============================================================
echo  Setup done! Run the bot with: start.bat
echo ============================================================
pause
