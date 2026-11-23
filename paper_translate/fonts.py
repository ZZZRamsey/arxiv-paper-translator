"""Detect and download a safe CJK fallback font for translated PDFs."""

import io
import zipfile
from pathlib import Path

import requests

FONT_URL = "https://github.com/notofonts/noto-cjk/releases/download/Sans2.004/18_NotoSansSC.zip"
FONT_DIR = Path.home() / "Library" / "Fonts" / "arxiv-translator"
FONT_FILE = FONT_DIR / "NotoSansCJKsc-Regular.otf"


def ensure_cjk_font(name, report=print):
    """Return a usable font file/name, downloading a permissive fallback when needed."""
    path = Path(name).expanduser()
    if path.is_file():
        return str(path)
    report(f"中文字体“{name}”未找到，将自动下载 Noto Sans CJK SC（约 50 MB，OFL 许可）")
    if FONT_FILE.is_file():
        report(f"使用已下载字体：{FONT_FILE}")
        return str(FONT_FILE)
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        response = requests.get(FONT_URL, timeout=(15, 300))
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            candidates = [n for n in archive.namelist()
                          if n.lower().endswith(".otf") and "regular" in n.lower()]
            if not candidates:
                candidates = [n for n in archive.namelist() if n.lower().endswith(".otf")]
            if not candidates:
                raise ValueError("下载包中没有可用的 OTF 字体")
            temporary = FONT_FILE.with_suffix(".download")
            temporary.write_bytes(archive.read(candidates[0]))
            temporary.replace(FONT_FILE)
    except (OSError, ValueError, zipfile.BadZipFile, requests.RequestException) as error:
        raise RuntimeError(f"无法自动下载中文字体：{error}。请安装 Songti SC 或指定已安装字体") from error
    report(f"中文字体已下载：{FONT_FILE}")
    return str(FONT_FILE)
