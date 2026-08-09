# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Intent OS Desktop."""

a = Analysis(
    ['intent_os_desktop/__init__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('intent_os_desktop/static', 'static'),
        ('intent_kernel', 'intent_kernel'),
    ],
    hiddenimports=[
        'intent_kernel',
        'intent_kernel.kernel',
        'intent_kernel.constitution',
        'intent_kernel.pkb',
        'intent_kernel.bus',
        'intent_kernel.router',
        'intent_kernel.providers',
        'intent_kernel.modules',
        'intent_kernel.monitor',
        'intent_kernel.persistence',
        'intent_kernel.capabilities',
        'intent_kernel.engine',
        'intent_kernel.server',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='IntentOS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
