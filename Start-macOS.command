#!/bin/zsh
set -eu
cd "${0:A:h}"
trap 'echo "Khong khoi chay duoc. Can Python 3.12 va Internet khi cai lan dau."; read "?Nhan Enter de dong..."' ZERR
if [[ ! -x .venv/bin/python ]]; then
  python3.12 -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -e .
.venv/bin/python -m tikbatch
