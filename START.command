#!/bin/bash
# macOS: double-click this file, or run: bash START.command
cd -- "$(dirname -- "$0")" || exit 1
export PYTHONUTF8=1

launcher_python=""
for candidate in "${FINANCEBP_PYTHON:-}" "./.venv/bin/python" python3.13 python3.14 python3; do
  [ -n "$candidate" ] || continue
  if "$candidate" -c 'import sys,struct; sys.exit(0 if sys.version_info[:2] in {(3,13),(3,14)} and struct.calcsize("P")==8 else 1)' 2>/dev/null; then
    launcher_python="$candidate"
    break
  fi
done

if [ -z "$launcher_python" ]; then
  /usr/bin/osascript -e 'display alert "财务分析：启动未完成" message "出错阶段：Python环境。未找到64位Python3.13或3.14。请安装包含pip、venv和Tk的完整Python，再双击START.command。" as critical'
  exit 1
fi

if [ "$#" -gt 0 ]; then
  "$launcher_python" scripts/manage.py "$@"
else
  "$launcher_python" scripts/desktop_launcher.py
fi
exit "$?"
