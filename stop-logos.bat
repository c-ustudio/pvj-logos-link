@echo off
rem Stops the Logos runtime started by this bridge. The next start gets a new Logos address.
set CTL=%LOCALAPPDATA%\logosctl\bin\logosctl.exe
where logosctl >NUL 2>NUL && set CTL=logosctl
"%CTL%" --config-dir "%~dp0session" daemon stop
pause
