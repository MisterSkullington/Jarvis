#!/usr/bin/env python3
"""
build_exe.py — Build a Windows .exe launcher for Jarvis using PyInstaller.

Usage:
    python scripts/build_exe.py

Produces: dist/Jarvis.exe

The .exe bundles start_all.py + mqtt_broker.py and all config files.
Run from the project root.  PyInstaller must be installed:
    pip install pyinstaller
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ------ PyInstaller spec -------------------------------------------------------
SPEC = """\
# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / 'scripts' / 'start_all.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'config'), 'config'),
        (str(ROOT / 'scripts' / 'mqtt_broker.py'), 'scripts'),
    ],
    hiddenimports=[
        'amqtt', 'amqtt.broker', 'amqtt.scripts.broker_script',
        'paho.mqtt.client',
        'services.nlu_agent.main', 'services.nlu_agent.memory',
        'services.nlu_agent.tools', 'services.nlu_agent.agent',
        'services.orchestrator.main',
        'services.scheduler.main',
        'services.stt.main',
        'services.tts.main',
        'services.wakeword.main',
        'jarvis_core', 'jarvis_core.config', 'jarvis_core.mqtt_helpers',
        'chromadb', 'sentence_transformers',
        'vosk', 'sounddevice', 'pyttsx3',
        'apscheduler', 'apscheduler.schedulers.background',
        'apscheduler.jobstores.sqlalchemy',
        'fastapi', 'uvicorn', 'httpx',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Jarvis',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Jarvis',
)
"""

spec_path = ROOT / "Jarvis.spec"
spec_path.write_text(SPEC)
print(f"Wrote {spec_path}")

result = subprocess.run(
    [sys.executable, "-m", "PyInstaller", "--clean", str(spec_path)],
    cwd=str(ROOT),
)

if result.returncode == 0:
    exe = ROOT / "dist" / "Jarvis" / "Jarvis.exe"
    print(f"\nBuild successful: {exe}")
    print("  Run it with:  dist\\Jarvis\\Jarvis.exe")
    print("  Or with flags: dist\\Jarvis\\Jarvis.exe --profile dev --no-vision")
else:
    print("\nBuild failed -- check PyInstaller output above.")
    sys.exit(1)
