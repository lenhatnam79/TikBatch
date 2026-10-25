"""Zip CI builds before artifact upload so app symlinks and modes survive."""
from pathlib import Path
import shutil
import subprocess
import sys
from tikbatch import __version__

root = Path(__file__).resolve().parent
release = root / "release"
release.mkdir(exist_ok=True)
if sys.platform == "darwin":
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                    str(root / "dist" / "TikBatch.app"),
                    str(release / f"TikBatch-{__version__}-macOS.zip")], check=True)
else:
    shutil.make_archive(str(release / f"TikBatch-{__version__}-Windows"), "zip",
                        root_dir=root / "dist", base_dir="TikBatch")
