"""Versioned arXiv acquisition and bounded extraction."""

import gzip
import hashlib
import io
import re
import stat
import tarfile
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit

import requests
from pypdf import PdfReader

BASE = "https://arxiv.org"
LIMIT = 256 * 1024 * 1024
IDENTIFIER = r"(?:\d{4}\.\d{4,5}|[a-zA-Z][a-zA-Z0-9.-]*/\d{7})(?:v[1-9]\d*)?"


def normalize(value):
    value = value.strip()
    if "://" in value:
        url = urlsplit(value)
        if url.scheme not in ("http", "https") or url.netloc.lower() not in (
            "arxiv.org", "www.arxiv.org"
        ):
            raise ValueError("需要 arxiv.org 的 abs/pdf URL 或 arXiv 编号")
        match = re.fullmatch(r"/(?:abs|pdf)/(.+)", unquote(url.path))
        value = match[1] if match else ""
    value = value.removeprefix("arXiv:").removesuffix(".pdf")
    if not re.fullmatch(IDENTIFIER, value):
        raise ValueError("无效 arXiv 编号")
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fetch(route, identifier):
    url = f"{BASE}/{route}/{identifier}"
    return fetch_same_version(url, identifier)


def fetch_same_version(url, identifier):
    current = url
    with requests.Session() as session:
        for _ in range(5):
            with session.get(current, stream=True, timeout=(15, 90),
                             allow_redirects=False) as response:
                if response.is_redirect:
                    current = urljoin(current, response.headers["Location"])
                    check_download_url(current, identifier)
                    continue
                return read_download(response, url, identifier)
    raise ValueError("arXiv 重定向次数超出限制")


def check_download_url(url, identifier):
    final = urlsplit(url)
    tail = unquote(final.path).split("/", 2)[-1].removesuffix(".pdf")
    if (final.scheme != "https" or final.netloc.lower() not in ("arxiv.org", "export.arxiv.org")
            or tail != identifier):
        raise ValueError(f"arXiv 重定向无法确认版本：{url}")


def read_download(response, url, identifier):
    check_download_url(response.url, identifier)
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError(f"arXiv 返回了意外的 HTTP 状态 {response.status_code}")
    data = bytearray()
    for chunk in response.iter_content(65536):
        data.extend(chunk)
        if len(data) > LIMIT:
            raise ValueError("下载超过大小上限")
    return bytes(data), {
        "url": url, "final_url": response.url, "status": response.status_code,
        "mime": response.headers.get("Content-Type"),
        "bytes": len(data), "sha256": digest(data),
        "utc": datetime.now(timezone.utc).isoformat(),
    }


class AbstractMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            fields = dict(attrs)
            key = fields.get("property")
            if key in ("og:title", "og:description"):
                self.fields[key] = " ".join((fields.get("content") or "").split())


def lock_version(identifier):
    page, metadata = fetch("abs", identifier)
    parser = AbstractMetadata()
    parser.feed(page.decode("utf-8"))
    parser.close()
    metadata["title"] = parser.fields.get("og:title", "")
    metadata["abstract"] = parser.fields.get("og:description", "")
    if re.search(r"v\d+$", identifier):
        return identifier, metadata
    versions = re.findall(rb"<strong>\s*(?:<a\b[^>]*>\s*)?\[v(\d+)\]", page)
    if not versions:
        raise ValueError("无法从 arXiv 提交记录确定版本")
    return f"{identifier}v{max(map(int, versions))}", metadata


def validate_pdf(data):
    if not data.startswith(b"%PDF-"):
        raise ValueError("响应不是 PDF")
    pages = len(PdfReader(io.BytesIO(data)).pages)
    if not pages:
        raise ValueError("PDF 没有页面")
    return pages


def extract(data, target):
    if data.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            data = stream.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("gzip 解压超过上限")
    if data.startswith(b"PK\x03\x04"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            unpack(((entry.filename, entry.file_size, entry.is_dir(),
                     stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR),
                     entry) for entry in archive.infolist()), archive.open, target)
        return
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    except tarfile.ReadError:
        if not re.search(rb"\\document(?:class|style)\b", data) or data.lstrip().startswith((b"<", b"%PDF")):
            raise ValueError("arXiv 响应不是可识别的 LaTeX 源码")
        target.mkdir()
        (target / "main.tex").write_bytes(data)
        return
    with archive:
        unpack(((entry.name, entry.size, entry.isdir(), entry.isdir() or entry.isfile(), entry)
                for entry in archive), archive.extractfile, target)


def unpack(entries, opener, target):
    files, directories, members = set(), set(), []
    size = 0
    for name, count, directory, regular, entry in entries:
        path = PurePosixPath(name)
        if path == PurePosixPath(".") and directory:
            continue
        if (not regular or path.is_absolute() or not path.parts or ".." in path.parts
                or any(c in name for c in ("\\", ":", "\x00"))):
            raise ValueError(f"不安全的归档成员：{name!r}")
        key = tuple(part.casefold() for part in path.parts)
        if key in files or key in directories:
            raise ValueError(f"重复归档成员：{name!r}")
        (directories if directory else files).add(key)
        members.append((path, key, directory, entry))
        size += count
        if len(members) > 10000 or size > LIMIT:
            raise ValueError("源码归档超过大小或文件数量上限")
    if any(key[:i] in files for _, key, _, _ in members for i in range(1, len(key))):
        raise ValueError("归档文件与目录冲突")
    target.mkdir()
    for path, _, directory, entry in members:
        output = target.joinpath(*path.parts)
        if directory:
            output.mkdir(parents=True, exist_ok=True)
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            with opener(entry) as stream, output.open("xb") as destination:
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        break
                    destination.write(chunk)
