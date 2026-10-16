@echo off
rem vmware-vm-control launcher (Windows).
rem Copies the server out of the Claude plugin folder before starting it, because Python builds that run
rem isolated (Microsoft Store / Python Install Manager) cannot read files under %%APPDATA%%\Claude.
rem Nothing may be printed to stdout here: stdout is the MCP channel.
setlocal
set "SRC=%~dp0"
set "DST=%USERPROFILE%\.vmware-vm-control\server"
if not exist "%DST%" mkdir "%DST%" >nul 2>nul
copy /y "%SRC%*.py" "%DST%\" >nul 2>nul
set "RUN=%DST%\vm_control.py"
if not exist "%RUN%" set "RUN=%SRC%vm_control.py"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%RUN%" %*
  exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
  python "%RUN%" %*
  exit /b
)
echo vmware-vm-control: Python 3 not found. Install it from python.org. 1>&2
exit /b 9009
