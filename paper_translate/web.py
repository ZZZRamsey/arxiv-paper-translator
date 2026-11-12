"""Local browser UI: a form over the same command line, one job at a time."""

import argparse
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from .sandbox import find_executable
from .settings import local_settings
from .source import normalize
from .translate import DEFAULT_MODEL, LOCAL_HOST, LOCAL_MODEL, OPENAI_ENDPOINT
from .zotero import attach_pdf as attach_to_zotero

PAGE = Path(__file__).with_name("web.html")
TOKEN = secrets.token_urlsafe(24)
FONTS = ("Songti SC", "Kaiti SC", "Heiti SC", "PingFang SC", "Hiragino Sans GB", "STSong", "STKaiti")
RESULT = re.compile(r"^PDF 已保存：(.+)$")
REPORT = re.compile(r"^验收报告：(.+)$")


class Job:
    """One translator subprocess and everything it has printed."""

    def __init__(self, command, environment, display, output, paper):
        self.display, self.output, self.paper = display, output, paper
        self.lines, self.status, self.pdf, self.report = [], "running", None, None
        self.started, self.finished = time.time(), None
        self.cancelled = False
        self.process = subprocess.Popen(
            command, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            bufsize=1, start_new_session=True,
        )
        threading.Thread(target=self.pump, daemon=True).start()

    def pump(self):
        for line in self.process.stdout:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            self.lines.append(line)
            match = RESULT.match(line)
            if match:
                self.pdf = match[1]
            match = REPORT.match(line)
            if match:
                self.report = match[1]
        code = self.process.wait()
        self.finished = time.time()
        self.status = "cancelled" if self.cancelled else "failed" if code else "done"

    def cancel(self):
        if self.status != "running":
            return
        self.cancelled = True
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def snapshot(self, since=0):
        archive = None
        if self.pdf:
            name = Path(self.pdf).name.replace("_zh_CN", "_zh_CN_latex", 1)
            candidate = Path(self.pdf).with_name(name).with_suffix(".zip")
            archive = str(candidate) if candidate.is_file() else None
        return {
            "status": self.status, "paper": self.paper, "command": self.display,
            "output": self.output, "pdf": self.pdf, "zip": archive, "report": self.report,
            "lines": self.lines[since:], "next": len(self.lines),
            "seconds": round((self.finished or time.time()) - self.started),
        }


class State:
    job = None
    lock = threading.Lock()


def settings():
    try:
        return local_settings(), None
    except (ValueError, OSError) as error:
        return {}, str(error)


def ollama_state():
    """What the local Ollama server has installed, asked fresh on every call."""
    host = os.getenv("OLLAMA_HOST") or LOCAL_HOST
    host = host if "://" in host else "http://" + host
    state = {"host": host, "host_from_env": bool(os.getenv("OLLAMA_HOST")), "models": None}
    try:
        found = requests.get(host + "/api/tags", timeout=1.5).json().get("models", [])
        try:
            running = requests.get(host + "/api/ps", timeout=1.5).json().get("models", [])
            loaded = {model.get("name") for model in running}
        except (requests.RequestException, ValueError, AttributeError):
            loaded = set()
        state["models"] = sorted(({
            "name": model["name"], "size": model.get("size", 0),
            "params": (model.get("details") or {}).get("parameter_size", ""),
            "quant": (model.get("details") or {}).get("quantization_level", ""),
            "vision": "vision" in (model.get("capabilities") or []),
            "loaded": model["name"] in loaded,
        } for model in found), key=lambda model: model["name"])
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        pass
    return state


def describe():
    config, problem = settings()
    pdftoppm = config.get("pdftoppm") or shutil.which("pdftoppm")
    return {
        "output": str(Path(config.get("output", "output")).expanduser().resolve()),
        "engine": "local" if config.get("local") is True else "openai" if config.get("openai") is True else "openrouter",
        "has_key": bool(os.getenv("OPENROUTER_API_KEY") or config.get("api_key")),
        "openai_has_key": bool(os.getenv("OPENAI_API_KEY") or config.get("openai_api_key")),
        "openai_base_url": os.getenv("OPENAI_BASE_URL") or config.get("openai_base_url") or OPENAI_ENDPOINT,
        "models": {"openrouter": os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL,
                   "openai": os.getenv("OPENAI_MODEL") or config.get("openai_model") or "gpt-4o-mini",
                   "local": os.getenv("OLLAMA_MODEL") or config.get("local_model") or LOCAL_MODEL},
        "local_model_source": ("环境变量 OLLAMA_MODEL" if os.getenv("OLLAMA_MODEL")
                               else "本机配置 local.json 的 local_model" if config.get("local_model")
                               else "程序内置默认值"),
        "ollama": ollama_state(),
        "fonts": FONTS,
        "tools": {"tectonic": bool(find_executable("tectonic")),
                  "texlive": bool(find_executable("pdflatex") and find_executable("xelatex")),
                  "pdftoppm": bool(pdftoppm and os.access(pdftoppm, os.X_OK))},
        "queue": str(Path("translation-queue").resolve()),
        "config_problem": problem,
        "running": bool(State.job and State.job.status == "running"),
    }


def folder(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"请填写{name}")
    return Path(value.strip()).expanduser().resolve()


def start(form):
    """Turn the form into the documented command line and launch it."""
    paper = str(form.get("paper", "")).strip()
    normalize(paper)
    engine = form.get("engine")
    if engine not in ("openrouter", "openai", "local"):
        raise ValueError("请选择翻译引擎")
    output = folder(form.get("output"), "保存位置")
    arguments = [paper, "--output", str(output)]
    environment = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONWARNINGS="ignore")
    if engine == "local":
        arguments.append("--local")
        if not form.get("review", True):
            arguments.append("--no-review")
    elif engine == "openai":
        arguments.append("--openai")
        key = str(form.get("api_key") or "").strip()
        if key:
            environment["OPENAI_API_KEY"] = key
        configured = describe()
        if not key and not configured["openai_has_key"] and configured["openai_base_url"].startswith("https://api.openai.com"):
            raise ValueError("OpenAI API 需要 API key，请填写后重试，或在本机配置中设置 openai_api_key")
    else:
        key = str(form.get("api_key") or "").strip()
        if key:
            environment["OPENROUTER_API_KEY"] = key
        elif not describe()["has_key"] and form.get("max_requests") != 0:
            raise ValueError("OpenRouter 需要 API key，请填写后重试，或改用本地模型")
    model = str(form.get("model") or "").strip()
    if model and engine != "chatgpt":
        arguments += ["--model", model]
    for name in ("original_layout", "texlive", "save_source", "zotero", "zotero_replace", "strict"):
        if form.get(name):
            arguments.append("--" + name.replace("_", "-"))
    jobs = form.get("jobs")
    if jobs not in (None, ""):
        if not isinstance(jobs, int) or not 1 <= jobs <= 8:
            raise ValueError("并发数需要在 1 到 8 之间")
        arguments += ["--jobs", str(jobs)]
    limit = form.get("max_requests")
    if limit not in (None, ""):
        if not isinstance(limit, int) or limit < 0:
            raise ValueError("请求上限不能小于 0")
        arguments += ["--max-requests", str(limit)]
    font = str(form.get("font") or "").strip()
    if font:
        if not re.fullmatch(r"[\w .-]+", font):
            raise ValueError("无效的中文字体名称")
        arguments += ["--font", font]
    root = str(form.get("root") or "").strip()
    if root:
        arguments += ["--root", root]
    overlay = str(form.get("tex_overlay") or "").strip()
    if overlay:
        arguments += ["--tex-overlay", str(folder(overlay, "本地宏包目录"))]
    display = "arxiv-translate " + " ".join(shlex.quote(part) for part in arguments)
    with State.lock:
        if State.job and State.job.status == "running":
            raise ValueError("已有翻译任务在运行，请等待完成或先取消")
        State.job = Job([sys.executable, "-u", "-m", "paper_translate", *arguments],
                        environment, display, str(output), paper)
    return State.job.snapshot()


def replace_in_zotero(path):
    """Attach an already translated PDF, moving older translations to the trash."""
    path = Path(str(path)).expanduser().resolve()
    match = re.fullmatch(r"(.+?)_zh_CN(?:_.*)?\.pdf", path.name)
    if not path.is_file() or not match:
        raise ValueError(f"不是本工具生成的译文 PDF：{path}")
    key, replaced = attach_to_zotero(path, match[1], None, True)
    return {"key": key, "replaced": replaced}


def recent(directory):
    directory = Path(directory).expanduser()
    if not directory.is_dir():
        return []
    files = sorted(directory.glob("*_zh_CN*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"path": str(path.resolve()), "name": path.name, "modified": path.stat().st_mtime,
             "size": path.stat().st_size} for path in files[:8]]


def pick_folder(current):
    script = 'POSIX path of (choose folder with prompt "选择文件夹"'
    if current and Path(current).expanduser().is_dir():
        script += " default location POSIX file " + json.dumps(str(Path(current).expanduser()))
    result = subprocess.run(["osascript", "-e", script + ")"], capture_output=True, text=True,
                            timeout=300, check=False)
    path = result.stdout.strip()
    return path.rstrip("/") or "/" if path else None


def reveal(path, in_finder):
    path = Path(str(path)).expanduser().resolve()
    allowed = path.is_dir() or (path.is_file() and path.suffix.lower() in (".pdf", ".zip", ".json"))
    if not allowed:
        raise ValueError(f"文件不存在或类型不支持：{path}")
    subprocess.run(["open", "-R", str(path)] if in_finder and path.is_file() else ["open", str(path)],
                   check=False)


class Handler(BaseHTTPRequestHandler):
    server_version = "arxiv-translate-ui"

    def log_message(self, *arguments):
        pass

    def reply(self, body, status=200, kind="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def trusted(self):
        """Only the page this server handed out may drive it."""
        host = self.headers.get("Host", "")
        local = host.rsplit(":", 1)[0] in ("127.0.0.1", "localhost")
        return local and secrets.compare_digest(self.headers.get("X-Token", ""), TOKEN)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/":
            host = self.headers.get("Host", "").rsplit(":", 1)[0]
            if host not in ("127.0.0.1", "localhost"):
                return self.reply({"error": "forbidden"}, 403)
            page = PAGE.read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            return self.reply(page.encode(), kind="text/html; charset=utf-8")
        if not path.startswith("/api/") or not self.trusted():
            return self.reply({"error": "forbidden"}, 403)
        if path == "/api/config":
            return self.reply(describe())
        if path == "/api/models":
            return self.reply(ollama_state())
        if path == "/api/job":
            since = int(query.partition("since=")[2] or 0) if query.startswith("since=") else 0
            return self.reply(State.job.snapshot(since) if State.job else {"status": "idle"})
        self.reply({"error": "not found"}, 404)

    def do_POST(self):
        if not self.trusted():
            return self.reply({"error": "forbidden"}, 403)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            form = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(form, dict):
                raise ValueError("请求格式错误")
            if self.path == "/api/start":
                return self.reply(start(form))
            if self.path == "/api/cancel":
                if State.job:
                    State.job.cancel()
                return self.reply({"ok": True})
            if self.path == "/api/pick-folder":
                return self.reply({"path": pick_folder(form.get("current"))})
            if self.path == "/api/open":
                reveal(form.get("path", ""), bool(form.get("reveal")))
                return self.reply({"ok": True})
            if self.path == "/api/zotero-replace":
                return self.reply(replace_in_zotero(form.get("path", "")))
            if self.path == "/api/recent":
                return self.reply({"files": recent(str(form.get("output") or ""))})
            self.reply({"error": "not found"}, 404)
        except (ValueError, OSError, RuntimeError, requests.RequestException,
                subprocess.SubprocessError) as error:
            self.reply({"error": str(error)}, 400)


def main():
    parser = argparse.ArgumentParser(description="在浏览器中使用 arXiv 论文翻译器")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="只启动服务，不自动打开浏览器")
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as error:
        parser.exit(1, f"错误：无法监听端口 {args.port}（{error}），可用 --port 换一个\n")
    address = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"界面已启动：{address}（Ctrl+C 退出）", flush=True)
    if not args.no_browser:
        threading.Timer(0.3, webbrowser.open, [address]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if State.job:
            State.job.cancel()
        server.server_close()


if __name__ == "__main__":
    main()
