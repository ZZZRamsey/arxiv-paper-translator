"""Offline TeX compilation with a macOS filesystem allowlist."""

import json
import os
import shutil
import sys
from pathlib import Path


def command_for(source, output, engine_args):
    engine = shutil.which("tectonic")
    if not engine or sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise ValueError("隔离编译需要 macOS sandbox-exec 和 Tectonic")
    cache = Path.home() / "Library/Caches/TectonicProject.Tectonic"
    if not cache.is_dir():
        raise ValueError("请先用可信的本地文档初始化 Tectonic 宏包缓存")
    engine = Path(engine).resolve()
    reads = [
        source.resolve(), output.resolve(), cache.resolve(), engine,
        Path("/System"), Path("/usr/lib"), Path("/usr/share"),
        Path("/private/var/db"), Path("/Library/Fonts"),
        Path("/opt/homebrew/Cellar"), Path("/usr/local/Cellar"),
        Path("/opt/homebrew/opt"), Path("/usr/local/opt"),
    ]
    profile = "\n".join([
        "(version 1)", "(allow default)", "(deny network*)",
        "(deny file-read-data)", "(deny file-write*)",
        "(allow file-read-data " + " ".join(
            f"(subpath {json.dumps(str(path), ensure_ascii=False)})" for path in reads
        ) + ' (literal "/") (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))',
        f"(allow file-write* (subpath {json.dumps(str(output.resolve()), ensure_ascii=False)}) (literal \"/dev/null\"))",
    ])
    env = {
        "HOME": str(Path.home()), "PATH": "/usr/bin:/bin",
        "TMPDIR": str(output.resolve()), "LANG": os.getenv("LANG", "en_US.UTF-8"),
    }
    return [
        "/usr/bin/sandbox-exec", "-p", profile, str(engine),
        "--untrusted", "--only-cached", *engine_args,
    ], env
