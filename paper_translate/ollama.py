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
# An 8-bit attention cache (which needs flash attention) trims the per-slot memory.
FIXED = {"LLAMA_ARG_CACHE_RAM": "0", "LLAMA_ARG_CTX_CHECKPOINTS": "2",
         "OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_FLASH_ATTENTION": "1"}
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


def local_host(url):
    return sys.platform == "darwin" and urlparse(url).hostname in ("127.0.0.1", "localhost", "::1")


def text_only(url, model):
    """A copy of a vision model without its image encoder (about 1 GB less memory).

    Translation never sends images. The copy shares the weight file on disk.
    """
    if not local_host(url):
        return model
    lines = output("ollama", "show", "--modelfile", model).splitlines()
    weights = [line for line in lines if line.startswith("FROM /")]
    if len(weights) < 2:
        return model
    name = model + "-text" if ":" in model else model + ":text"
    if name not in output("ollama", "list").split():
        keep = []
        for line in lines:
            if line.startswith("LICENSE"):
                break
            if line.startswith(("TEMPLATE", "RENDERER", "PARSER", "PARAMETER", "SYSTEM")):
                keep.append(line)
        created = subprocess.run(["ollama", "create", name, "-f", "/dev/stdin"],
                                 input="\n".join([weights[0], *keep]) + "\n",
                                 capture_output=True, text=True, check=False)
        if created.returncode:
            return model
        print(f"已创建不含视觉模块的翻译用模型 {name}", flush=True)
    return name


def ensure_server(url, jobs):
    """Restart Ollama with the needed settings unless it already runs with them."""
    if not local_host(url):
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
