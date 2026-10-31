@echo off
setlocal
pushd "%~dp0"
where cl >nul 2>&1
if not errorlevel 1 goto compile
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" goto missing
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSROOT=%%i"
if not defined VSROOT goto missing
call "%VSROOT%\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 goto failed
:compile
cl /nologo /std:c++17 /EHsc /O2 /MT /W4 /utf-8 /LD tsume.cpp /link /OUT:tsume.dll /MACHINE:X64
if errorlevel 1 goto failed
echo Built: %CD%\tsume.dll
popd
exit /b 0
:missing
echo Visual Studio C++ desktop tools are required.
:failed
popd
exit /b 1
