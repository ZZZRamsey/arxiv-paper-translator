"""Attach translated PDFs to matching items in the local Zotero library."""

import hashlib
import json
import mimetypes
from pathlib import Path
from urllib.parse import quote

import requests


class ZoteroLocalError(RuntimeError):
    """A local Zotero API operation could not be completed."""


class ZoteroLocal:
    def __init__(self, base_url="http://localhost:23119/api", timeout=30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Zotero-API-Version": "3",
            "Zotero-Allowed-Request": "1",
            "User-Agent": "arxiv-paper-translator/1.0",
        })
        response = self.session.get(self.base_url + "/", timeout=timeout)
        zotero_version = response.headers.get("X-Zotero-Version", "")
        if zotero_version and zotero_version.split(".", 1)[0].isdigit() \
                and int(zotero_version.split(".", 1)[0]) < 10:
            raise ZoteroLocalError(
                f"当前 Zotero 版本为 {zotero_version}，本机 API 写入需要 Zotero 10 或更高版本。"
            )
        if response.status_code == 403:
            raise ZoteroLocalError(
                "Zotero 本机 API 未启用。请在设置 → 高级中启用“允许本机其他应用与 Zotero 通信”。"
            )
        if response.status_code >= 400:
            raise ZoteroLocalError(f"无法连接 Zotero 本机 API：HTTP {response.status_code}")
        self.server_id = response.headers.get("Zotero-Server-ID")
        if not self.server_id:
            raise ZoteroLocalError("当前 Zotero 未提供可写 Local API 所需的 Server ID，请升级到 Zotero 10。")
        self.api_key = None

    def _headers(self, write=False):
        headers = {"Zotero-Server-ID": self.server_id}
        if write and self.api_key:
            headers["Zotero-API-Key"] = self.api_key
        return headers

    def _request(self, method, path, **kwargs):
        write = method.upper() != "GET"
        headers = self._headers(write)
        headers.update(kwargs.pop("headers", {}))
        response = self.session.request(method, self.base_url + path,
                                        headers=headers, timeout=self.timeout, **kwargs)
        if response.status_code == 401 and write:
            self._authorize()
            headers = self._headers(True)
            headers.update(kwargs.pop("headers", {}))
            response = self.session.request(method, self.base_url + path,
                                            headers=headers, timeout=self.timeout, **kwargs)
        if response.status_code >= 400:
            detail = response.text.strip()[:500]
            raise ZoteroLocalError(f"Zotero API {method} {path} 失败：HTTP {response.status_code} {detail}")
        return response

    def _authorize(self):
        response = self.session.post(
            self.base_url + "/local/authorize",
            headers={"Zotero-Server-ID": self.server_id,
                     "Zotero-Allowed-Request": "1"},
            json={"appName": "arXiv Paper Translator"}, timeout=self.timeout,
        )
        if response.status_code == 403:
            raise ZoteroLocalError("你拒绝了 Zotero 本机写入授权。")
        if response.status_code >= 400:
            raise ZoteroLocalError(f"无法取得 Zotero 写入授权：HTTP {response.status_code}")
        self.api_key = response.json()["key"]

    @staticmethod
    def _matches(item, arxiv_id, title):
        data = item.get("data", {})
        text = " ".join(str(data.get(key, "")) for key in ("title", "url", "extra", "DOI"))
        return arxiv_id.lower() in text.lower() or data.get("title", "").strip() == title.strip()

    def find_parent(self, arxiv_id, title):
        response = self._request("GET", "/users/0/items", params={
            "q": arxiv_id, "qmode": "everything", "itemType": "-attachment",
            "limit": 100, "format": "json",
        })
        matches = [item for item in response.json() if self._matches(item, arxiv_id, title)]
        if len(matches) != 1:
            raise ZoteroLocalError(
                f"按 {arxiv_id} 找到 {len(matches)} 个候选 Zotero 条目，已停止以避免挂错条目。"
            )
        return matches[0]

    def attach_pdf(self, pdf, arxiv_id, paper_title):
        pdf = Path(pdf).resolve(strict=True)
        if pdf.suffix.lower() != ".pdf":
            raise ZoteroLocalError(f"译文不是 PDF：{pdf}")
        parent = self.find_parent(arxiv_id, paper_title)
        parent_key = parent["key"]
        content = pdf.read_bytes()
        md5 = hashlib.md5(content).hexdigest()
        children = self._request("GET", f"/users/0/items/{quote(parent_key)}/children",
                                 params={"format": "json"}).json()
        for child in children:
            data = child.get("data", {})
            if data.get("md5") == md5:
                return child["key"]

        filename = pdf.name
        title = f"{paper_title} 中文译本"
        created = self._request("POST", "/users/0/items", json=[{
            "itemType": "attachment", "parentItem": parent_key,
            "linkMode": "imported_file", "title": title,
            "contentType": mimetypes.guess_type(filename)[0] or "application/pdf",
            "filename": filename, "md5": None, "mtime": None,
        }]).json()
        attachment_key = created.get("success", {}).get("0")
        if not attachment_key:
            raise ZoteroLocalError(f"Zotero 未返回新附件 key：{json.dumps(created, ensure_ascii=False)}")

        mtime = int(pdf.stat().st_mtime * 1000)
        file_path = f"/users/0/items/{quote(attachment_key)}/file"
        auth = self._request("POST", file_path, headers={"If-None-Match": "*"}, data={
            "md5": md5, "filename": filename, "filesize": str(len(content)), "mtime": str(mtime),
        }).json()
        if auth.get("exists") != 1:
            upload_url = auth.get("url")
            upload_key = auth.get("uploadKey")
            if not upload_url or not upload_key:
                raise ZoteroLocalError("Zotero 未返回文件上传地址")
            uploaded = self.session.post(upload_url, data=content,
                                         headers={"Content-Type": "application/pdf"},
                                         timeout=max(self.timeout, 120))
            if uploaded.status_code >= 400:
                raise ZoteroLocalError(f"上传译文 PDF 失败：HTTP {uploaded.status_code}")
            self._request("POST", file_path, headers={"If-None-Match": "*"},
                          data={"upload": upload_key})
        return attachment_key


def attach_pdf(pdf, arxiv_id, paper_title):
    return ZoteroLocal().attach_pdf(pdf, arxiv_id, paper_title)
