#!/usr/bin/env bash
set -euo pipefail

TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${MATERIAL_MATCHER_CURRENT_ROOT:-$(cd "$TOOL_DIR/.." && pwd)}"
SOURCE_WEB="$ROOT/source/web"
TARGET_DIST="$ROOT/web-dist"
SERVER_ENV="${MATERIAL_MATCHER_SERVER_ENV:-/etc/material_matcher/server.env}"
WORK="$(mktemp -d)"
NEXT_DIST="${TARGET_DIST}.next.$$"
BACKUP_DIST="${TARGET_DIST}.backup.$(date +%Y%m%d_%H%M%S)"
SWITCHED=0

cleanup() {
  rm -rf "$WORK" "$NEXT_DIST"
}
trap cleanup EXIT

fail() { echo "前端重建失败：$*" >&2; exit 2; }
[[ -d "$SOURCE_WEB" ]] || fail "未找到 Vue 源码：$SOURCE_WEB"
[[ -f "$SOURCE_WEB/package.json" && -f "$SOURCE_WEB/package-lock.json" ]] || fail "Vue 源码缺少 package.json/package-lock.json"

NODE_HOME="${MATERIAL_MATCHER_NODE_HOME:-$ROOT/tools/node-runtime}"
if [[ -x "$NODE_HOME/bin/node" ]]; then
  export PATH="$NODE_HOME/bin:$PATH"
elif ! command -v node >/dev/null 2>&1; then
  fail "未找到 Node runtime。请由 OpenCode 将离线 Node runtime 放到 $ROOT/tools/node-runtime，或设置 MATERIAL_MATCHER_NODE_HOME。"
fi
command -v npm >/dev/null 2>&1 || fail "未找到 npm。离线 Node runtime 需要包含 npm。"

node --version
npm --version
cp -a "$SOURCE_WEB/." "$WORK/"
rm -rf "$WORK/dist"

if [[ -d "$ROOT/tools/frontend-node_modules" ]]; then
  rm -rf "$WORK/node_modules"
  cp -a "$ROOT/tools/frontend-node_modules" "$WORK/node_modules"
elif [[ -d "$ROOT/tools/npm-cache" ]]; then
  (
    cd "$WORK"
    npm ci --offline --cache "$ROOT/tools/npm-cache" --no-audit --no-fund
  )
elif [[ -d "$WORK/node_modules" ]]; then
  echo "使用源码目录中已有的 node_modules。"
else
  fail "未找到离线前端依赖。请由 OpenCode 准备 tools/frontend-node_modules 或 tools/npm-cache；本工具绝不联网下载。"
fi

(
  cd "$WORK"
  npm run build
)
[[ -f "$WORK/dist/index.html" ]] || fail "npm build 未生成 dist/index.html"

mkdir -p "$(dirname "$TARGET_DIST")"
cp -a "$WORK/dist" "$NEXT_DIST"
[[ -f "$NEXT_DIST/index.html" ]] || fail "临时 dist 校验失败"

rollback() {
  if [[ $SWITCHED -eq 1 && -d "$BACKUP_DIST" ]]; then
    echo "健康检查失败，恢复旧前端……" >&2
    rm -rf "$TARGET_DIST"
    mv "$BACKUP_DIST" "$TARGET_DIST"
  fi
}

if [[ -d "$TARGET_DIST" ]]; then
  mv "$TARGET_DIST" "$BACKUP_DIST"
fi
mv "$NEXT_DIST" "$TARGET_DIST"
SWITCHED=1

PORT="18080"
if [[ -r "$SERVER_ENV" ]]; then
  VALUE="$(sed -n 's/^MATERIAL_MATCHER_PORT=//p' "$SERVER_ENV" | tail -1)"
  [[ "$VALUE" =~ ^[0-9]+$ ]] && PORT="$VALUE"
fi

if ! python3 - "$PORT" <<'PY'
import json, sys, urllib.request
port=int(sys.argv[1])
with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as response:
    health=json.load(response)
if health.get("status") != "ok":
    raise SystemExit(f"health 异常: {health}")
with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
    content=response.read(4096).lower()
if b"<html" not in content and b"<!doctype html" not in content:
    raise SystemExit("首页不是有效 HTML")
PY
then
  rollback
  exit 2
fi

SWITCHED=0
echo "前端重建并切换成功：$TARGET_DIST"
if [[ -d "$BACKUP_DIST" ]]; then
  echo "旧前端备份保留：$BACKUP_DIST"
fi
