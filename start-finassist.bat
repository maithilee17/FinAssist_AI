@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "PROJECT_DIR=%~dp0"
set "SCRIPT=%PROJECT_DIR%start-finassist.sh"

if not exist "%SCRIPT%" (
  echo ERROR: start-finassist.sh was not found beside this launcher.
  pause
  exit /b 1
)

set "GIT_BASH="
if exist "%ProgramFiles%\Git\bin\bash.exe" set "GIT_BASH=%ProgramFiles%\Git\bin\bash.exe"
if not defined GIT_BASH if exist "%ProgramFiles%\Git\usr\bin\bash.exe" set "GIT_BASH=%ProgramFiles%\Git\usr\bin\bash.exe"
if not defined GIT_BASH if exist "%LocalAppData%\Programs\Git\bin\bash.exe" set "GIT_BASH=%LocalAppData%\Programs\Git\bin\bash.exe"

if defined GIT_BASH (
  echo Starting FinAssist with Git Bash...
  "%GIT_BASH%" "%SCRIPT%"
  set "RESULT=!ERRORLEVEL!"
  goto :finished
)

where wsl.exe >nul 2>&1
if errorlevel 1 goto :no_bash
wsl.exe --list --quiet >nul 2>&1
if errorlevel 1 goto :no_bash

echo Git Bash was not found. Starting FinAssist with WSL...
wsl.exe --cd "%PROJECT_DIR%" --exec bash ./start-finassist.sh
set "RESULT=!ERRORLEVEL!"
goto :finished

:no_bash
echo ERROR: Neither Git Bash nor an initialized WSL distribution is available.
echo Install Git for Windows from https://git-scm.com/download/win
echo or install WSL and enable Docker Desktop WSL integration.
set "RESULT=1"

:finished
if not "%RESULT%"=="0" (
  echo.
  echo FinAssist did not start. Review the error above and the latest file in logs\.
  pause
)
exit /b %RESULT%
