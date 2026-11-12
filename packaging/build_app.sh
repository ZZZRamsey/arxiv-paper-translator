#!/bin/bash
# Build "arXiv Translator.app" and a .dmg from this checkout.
#
# Needs: macOS, Xcode Command Line Tools (swiftc, codesign, hdiutil), Homebrew with
# tectonic and poppler installed, and a Python 3.9+ to create the build environment.
# The app is ad-hoc signed; see docs/APP.zh-CN.md for signing and notarization.
set -euo pipefail
cd "$(dirname "$0")/.."

NAME="arXiv Translator"
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
BUILD=build
APP="dist/$NAME.app"
DMG="dist/arXiv-Translator-$VERSION-$(uname -m).dmg"

for tool in swiftc codesign hdiutil iconutil tectonic pdftoppm; do
  command -v "$tool" >/dev/null || { echo "缺少构建工具：$tool" >&2; exit 1; }
done

echo "==> Python 后端（PyInstaller）"
if [ ! -x .build-venv/bin/pyinstaller ]; then
  python3 -m venv .build-venv
  .build-venv/bin/pip install -q --upgrade pip
  .build-venv/bin/pip install -q pyinstaller
fi
.build-venv/bin/pip install -q "requests>=2.32,<3" "pypdf>=5,<7" "regex>=2024.11" "fonttools>=4.59,<5"
rm -rf "$BUILD" "$APP" "$DMG"
mkdir -p "$BUILD" dist
.build-venv/bin/pyinstaller --noconfirm --clean --log-level WARN \
  --name arxiv-translator-backend --onedir --console --paths "$PWD" \
  --hidden-import paper_translate.cli --hidden-import paper_translate.web \
  --add-data "$PWD/paper_translate/web.html:paper_translate" \
  --add-data "$PWD/paper_translate/verify.py:paper_translate" \
  --distpath "$BUILD/backend-dist" --workpath "$BUILD/backend-work" --specpath "$BUILD" \
  packaging/backend.py

echo "==> 应用外壳"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -o "$APP/Contents/MacOS/$NAME" packaging/Launcher.swift
cp -R "$BUILD/backend-dist/arxiv-translator-backend" "$APP/Contents/Resources/backend"

echo "==> 内置 Tectonic 和 Poppler"
python3 packaging/bundle_tools.py "$APP/Contents/Resources/tools" tectonic pdftoppm

echo "==> 图标"
swiftc -O -o "$BUILD/make-icon" packaging/MakeIcon.swift
ICONSET="$BUILD/AppIcon.iconset"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  "$BUILD/make-icon" "$size" "$ICONSET/icon_${size}x${size}.png"
  "$BUILD/make-icon" "$((size * 2))" "$ICONSET/icon_${size}x${size}@2x.png"
done
iconutil -c icns -o "$APP/Contents/Resources/AppIcon.icns" "$ICONSET"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleIdentifier</key><string>io.github.zzzramsey.arxiv-translator</string>
  <key>CFBundleExecutable</key><string>$NAME</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>$(sw_vers -productVersion | cut -d. -f1).0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>NSAppleEventsUsageDescription</key><string>用于显示选择文件夹的对话框。</string>
</dict></plist>
PLIST

echo "==> 签名（ad-hoc）"
codesign --force --deep --sign - "$APP"
codesign --verify --deep "$APP"

echo "==> 磁盘映像"
STAGE="$BUILD/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "$NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG"

du -sh "$APP" "$DMG"
echo "完成：$APP"
echo "      $DMG"
