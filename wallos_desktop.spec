# PyInstaller spec for Wallos Desktop
# Builds a standalone .exe with embedded icon, no console window, and all desktop modules

block_cipher = None

# Data files to include - relative to WALLOS_ROOT
datas = [
    ('wallos.ico', '.'),
    ('app', 'app'),
    ('endpoints', 'endpoints'),
    ('includes', 'includes'),
    ('api', 'api'),
    ('images', 'images'),
    ('styles', 'styles'),
    ('scripts', 'scripts'),
    ('libs', 'libs'),
    ('migrations', 'migrations'),
    ('webfonts', 'webfonts'),
    ('dev', 'dev'),
    ('db', 'db'),
    ('desktop', 'desktop'),
    ('wallos.ico', '.'),
]

# Hidden imports for pywebview and all desktop modules
hiddenimports = [
    'webview',
    'webview.platforms.edgechromium',
    'webview.platforms.winforms',
    'pystray',
    'PIL',
    'PIL.Image',
    'psutil',
    'win32api',
    'win32con',
    'win32gui',
    'win32com.client',
    'win10toast',
    'loguru',
    'cryptography',
    'cryptography.fernet',
    'desktop.php_server',
    'desktop.scheduler',
    'desktop.backup_manager',
    'desktop.data_manager',
    'desktop.app',
]

# Exclude unnecessary modules to reduce size
excludes = [
    'tkinter',
    'matplotlib',
    'numpy',
    'pandas',
    'scipy',
    'IPython',
    'jupyter',
    'notebook',
    'pytest',
    'unittest',
    'doctest',
    'pdb',
    'pydoc',
]

a = Analysis(
    ['desktop/app.py'],
    pathex=['.', 'desktop'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Wallos',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='wallos.ico',
    uac_admin=False,
    uac_uiaccess=False,
)