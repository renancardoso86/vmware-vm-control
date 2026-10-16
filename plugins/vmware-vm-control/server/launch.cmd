@echo off
rem vmware-vm-control launcher (Windows).
rem Copies the server out of the Claude plugin folder before starting it, because Python builds that run
rem isolated (Microsoft Store / Python Install Manager) cannot read files under %%APPDATA%%\Claude.
rem Python used, in order: the embeddable Python bundled in the release package (..\python), then the
rem installed "py" launcher, then "python" (skipping the Microsoft Store alias, which is not a real Python).
rem Nothing may be printed to stdout here: stdout is the MCP channel.
setlocal
set "SRC=%~dp0"
set "DST=%USERPROFILE%\.vmware-vm-control\server"
if not exist "%DST%" mkdir "%DST%" >nul 2>nul
copy /y "%SRC%*.py" "%DST%\" >nul 2>nul
set "RUN=%DST%\vm_control.py"
if not exist "%RUN%" set "RUN=%SRC%vm_control.py"
set "EMB=%SRC%..\python\python.exe"
if exist "%EMB%" (
  "%EMB%" -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    "%EMB%" "%RUN%" %*
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
echo vmware-vm-control: Python 3 not found. Use the release package (it bundles Python) or install Python 3 from python.org. 1>&2
exit /b 9009
