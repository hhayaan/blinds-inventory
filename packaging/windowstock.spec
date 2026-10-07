# Reusable Windows one-folder release. Generated files belong under release/.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata


project_root = Path(SPECPATH).resolve().parent
datas = [(str(project_root / "web"), "web")]
datas += collect_data_files("barcode")
for distribution in ("fastapi", "uvicorn", "SQLAlchemy", "python-barcode"):
    datas += copy_metadata(distribution, recursive=True)

analysis = Analysis(
    [str(project_root / "run.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.lifespan.on",
        "sqlalchemy.dialects.sqlite.pysqlite",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "_pytest", "httpx", "tkinter"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Windowstock",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="Windowstock",
)
