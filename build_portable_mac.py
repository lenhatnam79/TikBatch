"""Bundle a relocatable python-build-standalone runtime without Xcode tools.

Run from a venv backed by an Astral python-build-standalone runtime.
The default PyInstaller build.py remains preferred for CI/Windows.
"""
import importlib.metadata as metadata
import plistlib
import shutil
import sys
from pathlib import Path
from tikbatch import __version__


def main():
    if sys.platform != "darwin":
        raise SystemExit("This build targets macOS only.")
    root = Path(__file__).resolve().parent
    base = Path(sys.base_prefix)
    if not (base / "lib" / "libpython3.12.dylib").exists():
        raise SystemExit("Use the relocatable Python 3.12 distribution from python-build-standalone.")
    app = root / "dist" / "TikBatch.app"
    if app.exists():
        raise SystemExit("Destination already exists; move the previous build before rebuilding.")
    resources = app / "Contents" / "Resources"
    runtime = resources / "runtime"
    shutil.copytree(base, runtime, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    site = runtime / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    packages = ["PySide6-Essentials", "shiboken6", "httpx", "httpcore", "h11", "anyio",
                "idna", "certifi", "typing_extensions", "yt-dlp", "playwright", "pyee",
                "greenlet", "curl-cffi", "cffi", "pycparser", "av"]
    for name in packages:
        dist = metadata.distribution(name)
        for relative in dist.files or []:
            # Entry points outside site-packages are unnecessary in the app.
            if ".." in relative.parts or relative.suffix == ".pyc":
                continue
            src = Path(dist.locate_file(relative))
            dest = site / relative
            if src.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
    shutil.copytree(root / "tikbatch", site / "tikbatch",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(root / "run_app.py", resources / "run_app.py")
    for filename in ("README.md", "THIRD_PARTY_NOTICES.md"):
        if (root / filename).exists():
            shutil.copy2(root / filename, resources / filename)
    binary_dir = app / "Contents" / "MacOS"
    binary_dir.mkdir(parents=True)
    entry = binary_dir / "TikBatch"
    entry.write_text('#!/bin/zsh\nset -eu\nresources="${0:A:h:h}/Resources"\nexec "$resources/runtime/bin/python3.12" "$resources/run_app.py" "$@"\n')
    entry.chmod(0o755)
    with (app / "Contents" / "Info.plist").open("wb") as file:
        plistlib.dump({"CFBundleName": "TikBatch", "CFBundleDisplayName": "TikBatch",
            "CFBundleIdentifier": "local.tikbatch.desktop", "CFBundleExecutable": "TikBatch",
            "CFBundlePackageType": "APPL", "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__, "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True}, file)
    print(app)


if __name__ == "__main__":
    main()
