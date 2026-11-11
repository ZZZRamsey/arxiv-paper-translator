"""Give the local Ollama server the settings that parallel translation needs."""

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

PARALLEL = "OLLAMA_NUM_PARALLEL"
# Without these, the runner's prompt cache grows until a 16 GB Mac swaps and
# generation slows several-fold.
FIXED = {"LLAMA_ARG_CACHE_RAM": "0", "LLAMA_ARG_CTX_CHECKPOINTS": "2"}
APPS = (Path("/Applications/Ollama.app"), Path.home() / "Applications/Ollama.app")


def output(*command):
    return subprocess.run(command, capture_output=True, text=True, check=False).stdout


def server_settings():
    """Settings of the running server; None when no server is running."""
    pids = output("pgrep", "-f", "ollama serve").split()
    if not pids:
        return None
    environment = output("ps", "eww", "-o", "command=", "-p", pids[0])
    return dict(re.findall(rf"\b({PARALLEL}|{'|'.join(FIXED)})=(\S+)", environment))


def suitable(settings, jobs):
    try:
        parallel = int(settings.get(PARALLEL, "1"))
    except ValueError:
        return False
    return parallel >= jobs and all(settings.get(name) == value for name, value in FIXED.items())


def ensure_server(url, jobs):
    """Restart Ollama with the needed settings unless it already runs with them."""
    if sys.platform != "darwin" or urlparse(url).hostname not in ("127.0.0.1", "localhost", "::1"):
        return
    wanted = {PARALLEL: str(jobs), **FIXED}
    running = server_settings()
    if running is not None and suitable(running, jobs):
        return
    print(f"正在以 {jobs} 路并行设置{'重启' if running is not None else '启动'} Ollama", flush=True)
    for name, value in wanted.items():
        subprocess.run(["launchctl", "setenv", name, value], check=False)
    for pattern in ("Ollama.app/Contents/MacOS/Ollama", "ollama serve", "llama-server"):
        subprocess.run(["pkill", "-f", pattern], check=False)
    time.sleep(2)
    application = next((path for path in APPS if path.is_dir()), None)
    if application:
        # launchctl covers later launches from the Dock; --env covers this one.
        flags = [part for name, value in wanted.items() for part in ("--env", f"{name}={value}")]
        subprocess.run(["open", "-g", *flags, str(application)], check=False)
    else:
        subprocess.Popen(["ollama", "serve"], env={**os.environ, **wanted}, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            if requests.get(url.rstrip("/") + "/api/version", timeout=2).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError(f"Ollama 未能在 {url} 启动，请手动运行 ollama serve")
