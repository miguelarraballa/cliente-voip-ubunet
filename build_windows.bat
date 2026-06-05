@echo off
REM build_windows.bat — genera dist\UbutelVoIP\UbutelVoIP.exe
setlocal

set VENV=venv
set DIST=dist
set EXE=%DIST%\UbutelVoIP\UbutelVoIP.exe

echo =^> Activando venv...
call "%VENV%\Scripts\activate.bat"
if errorlevel 1 (
    echo ERROR: no se pudo activar el venv
    exit /b 1
)

echo =^> Convirtiendo icono a .ico...
python -c "from PIL import Image; img=Image.open('logo.png'); img.save('UbutelVoIP.ico', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
if errorlevel 1 (
    echo AVISO: no se pudo generar UbutelVoIP.ico. Instala Pillow: pip install pillow
    echo        Continuando sin icono personalizado...
    REM Crear un .ico vacío para que no falle PyInstaller
    copy NUL UbutelVoIP.ico >NUL 2>&1
)

echo =^> Limpiando builds anteriores...
if exist build rmdir /s /q build
if exist "%DIST%\UbutelVoIP" rmdir /s /q "%DIST%\UbutelVoIP"

echo =^> Compilando con PyInstaller...
pyinstaller UbutelVoIP_windows.spec --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller falló
    exit /b 1
)

if not exist "%EXE%" (
    echo ERROR: no se generó %EXE%
    exit /b 1
)

echo.
echo Build completado: %EXE%
echo.
echo ----------------------------------------------------------
echo   CONFIGURACION INICIAL (solo la primera vez):
echo.
echo   1. Las credenciales se guardan en:
echo      %%APPDATA%%\UbutelVoIP\
echo.
echo   2. En la primera ejecucion el dialogo de ajustes
echo      se abrira automaticamente para introducirlas.
echo.
echo   3. Ejecuta: %EXE%
echo ----------------------------------------------------------
endlocal
