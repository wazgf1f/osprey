"""Build a self-extracting Windows installer with a small UI.

Outputs:
    dist/Osprey-<version>-win64-portable.zip
    dist/Osprey-<version>-Setup.exe

The setup exe is a WinForms stub compiled with the .NET Framework csc that
ships with Windows, with payload.zip appended to it. No Inno/NSIS/7-Zip
required.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "0.1.0"
APP = ROOT / "dist" / "osprey"
PAYLOAD = ROOT / "dist" / "payload"
PORTABLE = ROOT / "dist" / ("Osprey-%s-win64-portable.zip" % VERSION)
SETUP_EXE = ROOT / "dist" / ("Osprey-%s-Setup.exe" % VERSION)
BUILD = ROOT.parent / ".build"
SETUP_SOURCE = ROOT / "packaging" / "setup_ui.cs"

MENU_BAT = r"""@echo off
chcp 936 >nul
cd /d "%~dp0"
title Osprey __VERSION__
:menu
cls
echo.
echo   Osprey __VERSION__  -  Windows 屏幕视觉自动化
echo.
echo   1. 环境自检（第一次先跑这个）
echo   2. 截取全屏
echo   3. 截取模板（从屏幕上框一块）
echo   4. 查找模板
echo   5. 运行任务
echo   6. 打开示例目录
echo   7. 打开中文上手指南
echo   8. 可视化编辑器（推荐）
echo   0. 退出
echo.
set "choice="
set /p "choice=请选择: "
if "%choice%"=="1" goto doctor
if "%choice%"=="2" goto grab
if "%choice%"=="3" goto crop
if "%choice%"=="4" goto find
if "%choice%"=="5" goto run
if "%choice%"=="6" goto examples
if "%choice%"=="7" goto guide
if "%choice%"=="8" goto editor
if "%choice%"=="0" exit /b 0
goto menu

:doctor
osprey.exe doctor
pause
goto menu

:grab
set "out="
set /p "out=保存文件名（例如 shot.png）: "
if not "%out%"=="" osprey.exe grab "%out%"
pause
goto menu

:crop
set "out="
set "region="
set /p "out=保存为模板（例如 button.png）: "
set /p "region=屏幕区域 x,y,w,h: "
if not "%out%"=="" if not "%region%"=="" osprey.exe crop "%out%" --region %region%
pause
goto menu

:find
set "tpl="
set /p "tpl=模板文件路径: "
if not "%tpl%"=="" osprey.exe find "%tpl%"
pause
goto menu

:run
set "task="
set "live="
set /p "task=任务文件路径（例如 examples\tasks\find_target.py）: "
set /p "live=真实点击？输入 y 确认，直接回车为 dry-run: "
if /i "%live%"=="y" (
  osprey.exe run "%task%" --live
) else (
  osprey.exe run "%task%"
)
pause
goto menu

:examples
start "" "%~dp0examples"
goto menu

:guide
start "" "%~dp0docs\quickstart.zh-CN.md"
goto menu

:editor
start "" "%~dp0osprey.exe" gui
goto menu
"""

UNINSTALL_BAT = r"""@echo off
chcp 936 >nul
if /i "%~1"=="--run" goto run
echo 正在卸载 Osprey...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Osprey" /f >nul 2>&1
del "%USERPROFILE%\Desktop\Osprey.lnk" >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Osprey.lnk" >nul 2>&1
copy "%~f0" "%TEMP%\osprey_uninstall.bat" >nul
start "" /b cmd /c ""%TEMP%\osprey_uninstall.bat" --run "%~dp0.""
echo 已清理快捷方式和注册表，程序目录会在后台删除。
exit /b 0

:run
timeout /t 1 >nul
rmdir /s /q "%~2"
del "%~f0" >nul 2>&1
exit /b 0
"""

SHORTCUTS_PS1 = r"""param([string]$Dest = "")

if (-not $Dest) { $Dest = $PSScriptRoot }

$target = Join-Path $Dest "osprey.bat"
$icon = Join-Path $Dest "osprey.exe"

try {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($dir in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
        if (-not $dir) { continue }
        if (-not (Test-Path -LiteralPath $dir)) { continue }
        try {
            $link = $shell.CreateShortcut((Join-Path $dir "Osprey.lnk"))
            $link.TargetPath = $target
            $link.WorkingDirectory = $Dest
            $link.IconLocation = $icon + ",0"
            $link.Description = "Osprey screen automation"
            $link.Save()
        } catch {
            Write-Warning ("shortcut not created in " + $dir + ": " + $_.Exception.Message)
        }
    }
} catch {
    Write-Warning ("shortcut shell unavailable: " + $_.Exception.Message)
}

try {
    $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Osprey"
    New-Item -Path $key -Force -ErrorAction Stop | Out-Null
    Set-ItemProperty -Path $key -Name DisplayName -Value "Osprey 0.1.0"
    Set-ItemProperty -Path $key -Name DisplayVersion -Value "0.1.0"
    Set-ItemProperty -Path $key -Name Publisher -Value "Osprey contributors"
    Set-ItemProperty -Path $key -Name InstallLocation -Value $Dest
    Set-ItemProperty -Path $key -Name DisplayIcon -Value $icon
    Set-ItemProperty -Path $key -Name UninstallString -Value ('"' + (Join-Path $Dest "uninstall.bat") + '"')
    New-ItemProperty -Path $key -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null
    New-ItemProperty -Path $key -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null
} catch {
    Write-Warning ("uninstall entry not created: " + $_.Exception.Message)
}

exit 0
"""


def write_gbk(path: Path, text: str) -> None:
    path.write_text(text.replace("__VERSION__", VERSION), encoding="gbk", newline="\r\n")


def write_utf8_sig(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8-sig", newline="\r\n")


def build_payload() -> None:
    if not APP.exists():
        raise SystemExit("dist/osprey is missing; run PyInstaller first")
    shutil.rmtree(PAYLOAD, ignore_errors=True)
    PAYLOAD.mkdir(parents=True)
    for item in APP.iterdir():
        target = PAYLOAD / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    shutil.copytree(ROOT / "examples", PAYLOAD / "examples")
    (PAYLOAD / "docs").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "docs" / "quickstart.zh-CN.md", PAYLOAD / "docs" / "quickstart.zh-CN.md")
    shutil.copy2(ROOT / "README.zh-CN.md", PAYLOAD / "README.zh-CN.md")
    write_gbk(PAYLOAD / "osprey.bat", MENU_BAT)
    write_gbk(PAYLOAD / "uninstall.bat", UNINSTALL_BAT)
    write_utf8_sig(PAYLOAD / "shortcuts.ps1", SHORTCUTS_PS1)


def make_zip(source: Path, target: Path) -> None:
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source))


def find_csc() -> Path:
    windows = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        Path(windows) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe",
        Path(windows) / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit("csc.exe (.NET Framework 4) was not found")


def compile_stub() -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    stub = BUILD / "osprey_setup_stub.exe"
    if stub.exists():
        stub.unlink()
    command = [
        str(find_csc()),
        "/nologo",
        "/target:winexe",
        "/codepage:65001",
        "/out:" + str(stub),
        "/r:System.dll",
        "/r:System.Core.dll",
        "/r:System.Drawing.dll",
        "/r:System.Windows.Forms.dll",
        "/r:System.IO.Compression.dll",
        "/r:System.IO.Compression.FileSystem.dll",
        str(SETUP_SOURCE),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0 or not stub.exists():
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        raise SystemExit("could not compile the installer UI")
    return stub


def build_setup() -> None:
    stub = compile_stub()
    payload = PORTABLE.read_bytes()
    if SETUP_EXE.exists():
        SETUP_EXE.unlink()
    with open(SETUP_EXE, "wb") as handle:
        handle.write(stub.read_bytes())
        handle.write(payload)
        handle.write(len(payload).to_bytes(8, "little"))


def main() -> int:
    build_payload()
    make_zip(PAYLOAD, PORTABLE)
    print("portable:", PORTABLE, "%.1f MB" % (PORTABLE.stat().st_size / 1e6))
    build_setup()
    print("setup   :", SETUP_EXE, "%.1f MB" % (SETUP_EXE.stat().st_size / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
