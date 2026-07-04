# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(os.path.abspath(SPECPATH))

# 收集数据文件
datas = [
    (str(ROOT_DIR / 'mijiaAPI_V2'), 'mijiaAPI_V2'),
    (str(ROOT_DIR / 'server'), 'server'),
    (str(ROOT_DIR / 'web' / 'dist'), 'web/dist'),
]

# 隐式导入
hiddenimports = [
    'mijiaAPI_V2',
    'mijiaAPI_V2.core',
    'mijiaAPI_V2.core.config',
    'mijiaAPI_V2.core.logging',
    'mijiaAPI_V2.domain',
    'mijiaAPI_V2.domain.models',
    'mijiaAPI_V2.domain.exceptions',
    'mijiaAPI_V2.infrastructure',
    'mijiaAPI_V2.infrastructure.http_client',
    'mijiaAPI_V2.infrastructure.crypto_service',
    'mijiaAPI_V2.infrastructure.cache_manager',
    'mijiaAPI_V2.infrastructure.credential_provider',
    'mijiaAPI_V2.infrastructure.credential_store',
    'mijiaAPI_V2.repositories',
    'mijiaAPI_V2.repositories.interfaces',
    'mijiaAPI_V2.repositories.device_repository',
    'mijiaAPI_V2.repositories.home_repository',
    'mijiaAPI_V2.repositories.scene_repository',
    'mijiaAPI_V2.repositories.device_spec_repository',
    'mijiaAPI_V2.services',
    'mijiaAPI_V2.services.auth_service',
    'mijiaAPI_V2.services.device_service',
    'mijiaAPI_V2.services.scene_service',
    'mijiaAPI_V2.services.statistics_service',
    'server',
    'server.app',
    'server.cli',
    'server.config',
    'server.db',
    'server.mijia_runtime',
    'server.security',
    'server.store',
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'fastapi',
    'pydantic',
    'httpx',
    'httpx_socks',
    'aiohttp',
    'tenacity',
    'cachetools',
    'Crypto',
    'Crypto.Cipher',
    'Crypto.Cipher.ARC4',
    'qrcode',
    'PIL',
    'PIL.Image',
]

a = Analysis(
    [str(ROOT_DIR / 'server' / 'cli.py')],
    pathex=[str(ROOT_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name='mijia-server',
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
    icon=str(ROOT_DIR / 'assets' / 'icon.ico'),
)
