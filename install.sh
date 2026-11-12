#!/bin/bash
# Install the command line (arxiv-translate) and the browser UI (arxiv-translate-ui).
#
#   ./install.sh              from a checkout
#   ./install.sh --with-deps  also install Tectonic and Poppler with Homebrew
#
# Everything goes into one private Python environment; nothing is installed system-wide.
# Prefer a double-clickable app? Download the .dmg from the Releases page instead.
set -euo pipefail

REPO="https://github.com/ZZZRamsey/arxiv-paper-translator.git"
PREFIX="${ARXIV_TRANSLATOR_HOME:-$HOME/.local/share/arxiv-paper-translator}"
BIN="${ARXIV_TRANSLATOR_BIN:-$HOME/.local/bin}"
WITH_DEPS=0
[ "${1:-}" = "--with-deps" ] && WITH_DEPS=1

say() { printf '%s\n' "$*"; }
fail() { printf '错误：%s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "目前只支持 macOS（编译依赖系统的 sandbox-exec）"
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
    PYTHON=$(command -v "$candidate"); break
  fi
done
[ -n "$PYTHON" ] || fail "需要 Python 3.9 或更高版本。可运行 xcode-select --install 或 brew install python"

HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)"
if [ -n "$HERE" ] && [ -f "$HERE/pyproject.toml" ]; then SOURCE="$HERE"; else SOURCE="git+$REPO"; fi

say "==> 安装到 $PREFIX（Python：$PYTHON）"
mkdir -p "$PREFIX" "$BIN"
"$PYTHON" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install -q --upgrade pip
"$PREFIX/venv/bin/pip" install -q --upgrade "$SOURCE"
for command in arxiv-translate arxiv-translate-ui; do
  ln -sf "$PREFIX/venv/bin/$command" "$BIN/$command"
done

if [ "$WITH_DEPS" = 1 ]; then
  command -v brew >/dev/null || fail "没有找到 Homebrew，请先按 https://brew.sh 安装，或手动安装 Tectonic 和 Poppler"
  say "==> 用 Homebrew 安装 Tectonic 和 Poppler"
  brew install tectonic poppler
fi

say ""
say "安装完成。"
missing=0
command -v tectonic >/dev/null || [ -x /Library/TeX/texbin/pdflatex ] || { say "  还需要 TeX 引擎：brew install tectonic"; missing=1; }
command -v pdftoppm >/dev/null || { say "  还需要 Poppler：brew install poppler"; missing=1; }
[ "$missing" = 1 ] && say "  （或重新运行 ./install.sh --with-deps 一并安装）"
case ":$PATH:" in *":$BIN:"*) ;; *) say "  请把 $BIN 加入 PATH：echo 'export PATH=\"$BIN:\$PATH\"' >> ~/.zshrc" ;; esac
say ""
say "打开界面：  arxiv-translate-ui"
say "命令行翻译：arxiv-translate 2503.09516 --fetch-packages"
