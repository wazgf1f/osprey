# Building the Windows package

The shipped artifacts are built from source on Windows with Python 3.10-3.12.

## 1. Build the standalone app

PyInstaller 6+ is required (the build uses --contents-directory . so all
runtime files sit next to the executable).

    python -m pip install pyinstaller
    python -m PyInstaller --noconfirm --clean --onedir --console ^
        --name osprey --paths src --contents-directory . ^
        --hidden-import osprey.gui --collect-submodules osprey ^
        --distpath dist --workpath ..\.build\pyi --specpath ..\.build ^
        packaging\entry.py

Result: dist\osprey (about 67 MB, includes Python, NumPy and Pillow).

## 2. Build the installer and portable zip

    python packaging\build_installer.py

Outputs:

- dist\Osprey-1.0.1-Setup.exe - self-extracting installer
- dist\Osprey-1.0.1-win64-portable.zip - same payload, no installation

The installer is a WinForms application (packaging/setup_ui.cs) compiled with
the .NET Framework csc that ships with Windows. The payload zip is appended to
the exe; on launch it shows the terms of use, an install path picker and a
progress bar. Nothing is installed until the user ticks the agreement box and
clicks the install button.

## Installer behaviour

- The user must accept the terms (which forbid attendance fraud) before the
  install button is enabled.
- The install path is editable, with a folder picker.
- No administrator rights are needed; everything is per-user.
- `/S` runs a silent install and `/D=path` sets the destination.
- A log is written to %TEMP%\osprey-setup.log.
- OSPREY_TEST_DEST overrides the install directory (used by the build tests).
- OSPREY_NO_SHORTCUTS=1 skips shortcuts and the registry entry.
- OSPREY_NO_LAUNCH=1 does not start the menu after installing.
- OSPREY_NO_PAUSE=1 skips the final "Press Enter" prompt.

## Packaging notes

- The setup executable is unsigned. Sign it with signtool before distributing
  widely if you have a certificate.
- PyInstaller bundles the VC runtime and UCRT, so the target machine needs no
  Python or Visual C++ redistributable.
- Windows 10/11 x64 only.
