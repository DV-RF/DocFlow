@echo off
title DocFlow — Build
echo.
echo  =============================================
echo   Construindo DocFlow.exe com PyInstaller
echo  =============================================
echo.

:: Instala dependências
pip install -r requirements.txt

:: Remove builds anteriores
if exist dist\DocFlow rmdir /s /q dist\DocFlow
if exist build      rmdir /s /q build

:: Gera o executável
pyinstaller ^
  --noconfirm ^
  --onedir ^
  --windowed ^
  --name "DocFlow" ^
  --icon "assets\icone.ico" ^
  --add-data "assets;assets" ^
  --collect-all "customtkinter" ^
  --hidden-import "pystray" ^
  --hidden-import "winotify" ^
  --hidden-import "PIL" ^
  --hidden-import "fitz" ^
  --hidden-import "pytesseract" ^
  --hidden-import "send2trash" ^
  main.py

echo.
echo  =============================================
echo   Pronto!  Pasta gerada: dist\DocFlow
echo  =============================================
echo.
pause
