#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$task_root"
task_python=${PYTHON:-python3}
"$task_python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "需要 Python 3.11+")'
"$task_python" -m venv .venv
.venv/bin/python -m pip install .
chmod +x duebridge homework
printf '\n安装完成。运行 ./duebridge init --preset zju，再运行 ./duebridge doctor。\n'
