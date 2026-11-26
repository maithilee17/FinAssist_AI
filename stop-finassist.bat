@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "PROJECT_DIR=%~dp0"
set "SCRIPT=%PROJECT_DIR%stop-finassist.sh"

if not exist "%SCRIPT%" (
  echo ERROR: stop-finassist.sh was not found beside this launcher.
  pause
  exit /b 1
)

set "GIT_BASH="
if exist "%ProgramFiles%\Git\bin\bash.exe" set "GIT_BASH=%ProgramFiles%\Git\bin\bash.exe"
if not defined GIT_BASH if exist "%ProgramFiles%\Git\usr\bin\bash.exe" set "GIT_BASH=%ProgramFiles%\Git\usr\bin\bash.exe"
if not defined GIT_BASH if exist "%LocalAppData%\Programs\Git\bin\bash.exe" set "GIT_BASH=%LocalAppData%\Programs\Git\bin\bash.exe"

if defined GIT_BASH (
  "%GIT_BASH%" "%SCRIPT%"
  set "RESULT=!ERRORLEVEL!"
  goto :finished
)

where wsl.exe >nul 2>&1
if errorlevel 1 goto :no_bash
wsl.exe --list --quiet >nul 2>&1
if errorlevel 1 goto :no_bash
wsl.exe --cd "%PROJECT_DIR%" --exec bash ./stop-finassist.sh
set "RESULT=!ERRORLEVEL!"
goto :finished

:no_bash
echo ERROR: Neither Git Bash nor an initialized WSL distribution is available.
set "RESULT=1"

:finished
if not "%RESULT%"=="0" pause
exit /b %RESULT%
