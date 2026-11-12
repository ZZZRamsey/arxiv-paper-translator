"""Offline TeX compilation with a macOS filesystem allowlist."""

import json
import os
import re
import shutil
import sys
from pathlib import Path

from .runtime import tools_root


def find_executable(name):
    candidates = []
    tools = tools_root()
    if tools:
        candidates.append(tools / "bin" / name)  # the copy shipped inside the app
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    candidates.extend([
        Path(sys.executable).parent / name,
        Path("/opt/homebrew/bin") / name,  # a Finder-launched app has no Homebrew PATH
        Path("/usr/local/bin") / name,
        Path("/Library/TeX/texbin") / name,
        Path("/usr/local/texlive/bin/universal-darwin") / name,
    ])
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            # Keep the pdflatex/xelatex symlink name so TeX selects the right format.
            return candidate.absolute()
    return None


def detect_engine(source, root=None):
    """Choose PDFLaTeX for sources that explicitly require pdfTeX."""
    candidates = [root] if root else []
    if root and root.is_file():
        root_text = root.read_text(encoding="utf-8", errors="replace")
        if "ARXIV_TRANSLATOR_XETEX" in root_text:
            return "tectonic"
    candidates.extend(sorted(source.rglob("*.cls")))
    candidates.extend(sorted(source.rglob("*.sty")))
    for path in candidates:
        if not path or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\\RequirePDFTeX\b|pdfTeX is required", text):
            return "pdflatex"
    return "tectonic"


def command_for(source, output, engine_args, engine=None):
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise ValueError("隔离编译需要 macOS sandbox-exec")
    engine = engine or detect_engine(source)
    if engine not in {"tectonic", "pdflatex", "xelatex", "bibtex"}:
        raise ValueError(f"不支持的 TeX 编译引擎：{engine}")
    executable = find_executable(engine)
    if not executable:
        if engine == "pdflatex":
            raise ValueError("源码要求 PDFLaTeX，但当前环境未找到 pdflatex。请安装 BasicTeX 或 MacTeX")
        raise ValueError(f"未找到 TeX 编译引擎：{engine}")
    cache = Path.home() / "Library/Caches/TectonicProject.Tectonic"
    if engine == "tectonic" and not cache.is_dir():
        raise ValueError("请先用可信的本地文档初始化 Tectonic 宏包缓存")
    reads = [source.resolve(), output.resolve(), executable,
             Path("/Library/TeX"), Path("/usr/local/texlive"),
             Path("/System"), Path("/usr/lib"), Path("/usr/share"),
             Path("/private/var/db"), Path("/Library/Fonts"),
             Path.home() / "Library/Fonts", Path.home() / "Library/texmf",
             Path.home() / "Library/texlive", Path("/opt/homebrew/Cellar"),
             Path("/usr/local/Cellar"), Path("/opt/homebrew/opt"),
             Path("/usr/local/opt")]
    # A relocatable TeX Live tree may live outside the standard installation paths.
    if tools_root():
        reads.append(tools_root())
    tex_root = executable.resolve().parent.parent.parent
    if (tex_root / "texmf-dist").is_dir():
        reads.append(tex_root)
    if cache.is_dir():
        reads.append(cache.resolve())
    for name in ("TEXMFHOME", "TEXMFVAR", "TEXMFCONFIG", "TEXMFROOT",
                 "TEXMFCNF", "TEXMFSYSVAR", "TEXMFSYSCONFIG"):
        value = os.getenv(name)
        if value:
            for item in value.split(os.pathsep):
                path = Path(item).expanduser()
                if path.exists():
                    reads.append(path.resolve())
    reads = [
        path for path in reads if path.exists()
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
        "HOME": str(Path.home()),
        "PATH": f"{executable.parent}:/Library/TeX/texbin:/usr/local/texlive/bin/universal-darwin:/usr/bin:/bin",
        "TMPDIR": str(output.resolve()), "LANG": os.getenv("LANG", "en_US.UTF-8"),
    }
    for name in ("TEXMFHOME", "TEXMFVAR", "TEXMFCONFIG", "TEXMFROOT", "TEXMFCNF",
                 "TEXMFSYSVAR", "TEXMFSYSCONFIG"):
        if os.getenv(name):
            env[name] = os.environ[name]
    command = ["/usr/bin/sandbox-exec", "-p", profile, str(executable)]
    if engine == "tectonic":
        command.extend(["--untrusted", "--only-cached"])
    command.extend(engine_args)
    return command, env
