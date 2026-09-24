# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata

datas = [('icon/Feuerdrache.ico', 'icon'), ('help.html', '.'), ('Handbuch/Handbuch.pdf', 'Handbuch'), ('Aenderungshistorie/CHANGELOG.json', 'Aenderungshistorie'), ('Aenderungshistorie/CHANGELOG.txt', 'Aenderungshistorie'), ('Aenderungshistorie/CHANGELOGV8.txt', 'Aenderungshistorie'), ('Aenderungshistorie/CHANGELOGV7.txt', 'Aenderungshistorie'), ('Bilder/banner.png', 'Bilder'), ('Bilder/splash_Intro.png', 'Bilder'), ('third_party/rmts', 'Programme/rmts'), ('third_party/HandBrake', 'Programme/handbrake'), ('dragontools/config', 'dragontools/config'), ('third_party/MKVToolNix', 'Programme/mkvtoolnix'), ('third_party/MakeMKV', 'Programme/MakeMKV')]
binaries = [('third_party/FFmpeg/ffmpeg.exe', 'Programme'), ('third_party/FFmpeg/ffprobe.exe', 'Programme'), ('third_party/GPAC/mp4box.exe', 'Programme'), ('third_party/dovi_tool/dovi_tool.exe', 'Programme'), ('third_party/hdr10plus_tool/hdr10plus_tool.exe', 'Programme'), ('third_party/Mediainfo/MediaInfo.exe', 'Programme')]
hiddenimports = ['cv2', 'faster_whisper', 'ctranslate2']
datas += collect_data_files('cv2')
datas += collect_data_files('cryptography')
datas += copy_metadata('faster-whisper')
datas += copy_metadata('ctranslate2')
binaries += collect_dynamic_libs('cv2')
binaries += collect_dynamic_libs('cryptography')
hiddenimports += collect_submodules('cv2')
hiddenimports += collect_submodules('cryptography')
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['DragonToolsV9.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PySide6', 'PySide2', 'PyQt6.QtWebEngineWidgets'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
splash = Splash(
    'Bilder/splash_pyinstaller.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    [],
    exclude_binaries=True,
    name='DragonToolsV9.8.6',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon/Feuerdrache.ico'],
    contents_directory='Daten',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    splash.binaries,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DragonToolsV9.8.6',
)
