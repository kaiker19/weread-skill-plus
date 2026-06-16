#!/usr/bin/env bash
# build_macos.sh —— Mac 本地打包：前端构建 → PyInstaller onedir → .app → .dmg
# 开发期隔离，整体未完成前不进 git。仅 macOS。用 hdiutil，无需 create-dmg。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"   # 仓库根
cd "$ROOT"

echo "==> 1/4 构建前端"
( cd web/frontend && npm ci && npm run build )

echo "==> 2/4 PyInstaller 打包（onedir）"
pip show pyinstaller >/dev/null 2>&1 || pip install pyinstaller
pyinstaller web/standalone/weread-dashboard.spec --noconfirm --clean

APPDIR="dist/WeReadDashboard"
[ -d "$APPDIR" ] || { echo "✗ 未生成 $APPDIR"; exit 1; }

echo "==> 3/4 冒烟：启动二进制并探活"
"$APPDIR/WeReadDashboard" >/tmp/weread_pkg.log 2>&1 &
PID=$!
sleep 6
PORT=$(grep -oE "127.0.0.1:[0-9]+" /tmp/weread_pkg.log | head -1 | cut -d: -f2 || true)
if [ -n "${PORT:-}" ] && curl -fsS "http://127.0.0.1:$PORT/api/stats" >/dev/null; then
  echo "  ✓ 二进制可启动且 API 可达（端口 $PORT）"
else
  echo "  ✗ 二进制启动探活失败，见 /tmp/weread_pkg.log"; kill $PID 2>/dev/null || true; exit 1
fi
kill $PID 2>/dev/null || true

echo "==> 4/4 打 .dmg"
DMG="dist/WeReadDashboard.dmg"
rm -f "$DMG"
hdiutil create -volname "WeRead Dashboard" -srcfolder "$APPDIR" -ov -format UDZO "$DMG"
echo "✓ 完成：$DMG"
echo "  分发前提醒：未签名，用户首次需「右键→打开」（见 BUILD.md / 放行图文）。"
