"""Build on the target OS. PyInstaller cannot cross-compile Windows on macOS."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parent
scratch = Path(tempfile.mkdtemp(prefix="tikbatch-build-"))
args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "TikBatch", "--paths", str(root),
        "--collect-all", "playwright", "--collect-all", "av",
        "--collect-all", "curl_cffi", "--collect-submodules", "yt_dlp",
        "--exclude-module", "tkinter", "--exclude-module", "IPython",
        "--exclude-module", "matplotlib", "--exclude-module", "numpy",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtQuick",
        "--distpath", str(root / "dist"), "--workpath", str(scratch / "build"),
        "--specpath", str(scratch)]
if sys.platform == "darwin":
    args += ["--windowed"]
if sys.platform == "darwin":
    args += ["--osx-bundle-identifier", "local.tikbatch.desktop"]
args += [str(root / "run_app.py")]
subprocess.run(args, cwd=root, check=True)
