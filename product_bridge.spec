# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['product_bridge.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['openai', 'intent_kernel'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='IntentOS.Bridge', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, console=False, disable_windowed_traceback=False,
)
