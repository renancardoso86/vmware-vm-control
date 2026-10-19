@echo off
rem vmware-vm-control launcher (Windows).
rem Copies the server out of the Claude plugin folder before starting it, because Python builds that run
rem isolated (Microsoft Store / Python Install Manager) cannot read files under %%APPDATA%%\Claude.
rem Python used, in order: the embeddable Python bundled in the release package (..\python), the one downloaded
rem earlier by get-python.ps1, the installed "py" launcher, "python" (skipping the Microsoft Store alias, which is
rem not a real Python); with none of them, get-python.ps1 downloads the official embeddable Python once.
rem Nothing may be printed to stdout here: stdout is the MCP channel.
setlocal
set "SRC=%~dp0"
set "HOME_DIR=%USERPROFILE%\.vmware-vm-control"
set "DST=%HOME_DIR%\server"
if not exist "%DST%" mkdir "%DST%" >nul 2>nul
copy /y "%SRC%*.py" "%DST%\" >nul 2>nul
set "RUN=%DST%\vm_control.py"
if not exist "%RUN%" set "RUN=%SRC%vm_control.py"
set "EMB=%SRC%..\python\python.exe"
set "DLPY=%HOME_DIR%\python\python.exe"
if exist "%EMB%" (
  "%EMB%" -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    "%EMB%" "%RUN%" %*
    exit /b
  )
)
if exist "%DLPY%" (
  "%DLPY%" -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    "%DLPY%" "%RUN%" %*
    exit /b
  )
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%RUN%" %*
  exit /b
)
python -c "import sys" >nul 2>nul
if not errorlevel 1 (
  python "%RUN%" %*
  exit /b
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%SRC%get-python.ps1" -Dest "%HOME_DIR%\python" 1>&2
if exist "%DLPY%" (
  "%DLPY%" "%RUN%" %*
  exit /b
)
echo vmware-vm-control: Python 3 not found and could not be downloaded. Install Python 3 from python.org, or use the release package (it bundles Python). 1>&2
exit /b 9009
