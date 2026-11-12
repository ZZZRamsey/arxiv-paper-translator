"""Fill Tectonic's package cache from documents this program writes itself.

Paper sources are compiled offline in a sandbox, so every TeX file they need must
already be cached. Only the generated documents below ever run with network access;
they contain nothing but package names that passed NAME.
"""

import re
import subprocess
import tempfile
from pathlib import Path

from .sandbox import find_executable

CACHE = Path.home() / "Library/Caches/TectonicProject.Tectonic"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,60}\.(?:sty|cls|def|clo|cfg|fd|tex|bst|ldf|enc|tfm|vf|otf|ttf|pfb|map|bbx|cbx)")
MISSING = re.compile(r"File [`']([^`'\n]+)' not found|I can't find file [`']([^`'\n]+)'"
                     r"|Font \S+?=(\[?[A-Za-z0-9._-]+\]?)[^\n]*?not loadable"
                     r"|physical font for TFM \"([A-Za-z0-9._-]+)\""
                     r"|find TFM file \"([A-Za-z0-9._-]+)\""
                     r"|(?:PK font \"|find this font: |open font file \"|read encoding file: )([A-Za-z0-9._-]+\.(?:pfb|otf|ttf|vf|map|enc))")
# What most arXiv templates and the Chinese build load.
COMMON = ("amsmath amssymb amsthm mathtools bm graphicx xcolor hyperref url natbib cite booktabs "
          "multirow array tabularx longtable colortbl makecell caption subcaption float wrapfig "
          "algorithm algorithmic algpseudocode listings enumitem geometry fancyhdr titlesec "
          "microtype xspace etoolbox silence times helvet courier txfonts newtxtext newtxmath "
          "fontenc inputenc textcomp lmodern tikz pgfplots soul ulem cleveref balance setspace "
          "pifont amsfonts bbm dsfont mathrsfs stmaryrd threeparttable adjustbox footmisc "
          "xeCJK fontspec xunicode accsupp axessibility").split()


# Typesetting real text and math at every size is what makes Tectonic fetch the font files.
SIZES = r"\tiny \scriptsize \footnotesize \small \normalsize \large \Large \LARGE \huge \Huge".split()
SAMPLE = (r"Text \textbf{bold \textit{both}} \textit{italic} \textsc{caps} \textsf{sans \textbf{b}} "
          r"\texttt{mono} $a^{b^c}_i + \sum\int\prod \alpha\beta\Gamma \mathcal{L} \mathbf{x} "
          r"\mathrm{d} \mathit{v} \sqrt{\frac{1}{2}} \leq \infty$")
BODY = "\n".join(f"{{{size} {SAMPLE}}}\\par" for size in SIZES)


def document(packages, body="x", preamble=""):
    lines = [r"\documentclass{article}"]
    # No \IfFileExists guard: it can answer "no" for a file that is merely not cached yet.
    # A package the bundle lacks is an error the run continues past.
    lines += [rf"\usepackage{{{name}}}" for name in packages]
    return "\n".join(lines + [preamble, r"\begin{document}", body, r"\end{document}", ""])


def run(tex, report):
    """Compile one generated document with network access; errors are tolerated."""
    tectonic = find_executable("tectonic")
    if not tectonic:
        raise ValueError("未找到 Tectonic，无法下载 TeX 宏包")
    with tempfile.TemporaryDirectory(prefix="arxiv-translator-tex-") as directory:
        path = Path(directory) / "fetch.tex"
        path.write_text(tex, encoding="utf-8")
        result = subprocess.run([str(tectonic), "-Z", "continue-on-errors", "--keep-logs",
                                 "--outdir", directory, path.name],
                                cwd=directory, capture_output=True, text=True, timeout=1800,
                                check=False)
        if result.returncode and re.search(r"error sending request|dns error|failed to (?:lookup|connect)|"
                                           r"could not resolve|timed out",
                                           result.stdout + result.stderr, re.IGNORECASE):
            raise ValueError("下载 TeX 宏包失败：无法连接 Tectonic 宏包服务器，请检查网络后重试")
        for line in (result.stdout + result.stderr).splitlines():
            if line.startswith("note: downloading") or line.startswith("note: Downloading"):
                report("下载" + line.split("ownloading", 1)[1])
        return result.returncode == 0


def warm(report=print):
    """First use: fetch the format and the packages most papers need."""
    report("正在下载 TeX 基础宏包（仅首次，需要联网，通常 5–15 分钟，取决于网络）")
    # One package per document keeps an option clash in one from hiding the others.
    run(document((), BODY), report)
    run(document(("amssymb", "amsmath", "bm"), BODY + r"\par$\mathbb{R}\mathfrak{g}\boldsymbol{\theta}\gtrsim$"), report)
    for fonts in (("lmodern",), ("times",), ("newtxtext", "newtxmath")):
        run(document(fonts, BODY), report)
    run(document(("xeCJK",), "中文 \\textbf{粗体} $x$", r"\setCJKmainfont{Songti SC}"), report)
    run(document(COMMON), report)
    for name in ("hyperref", "natbib", "tikz"):
        run(document((name,)), lambda line: None)
    if not CACHE.is_dir():
        raise ValueError("TeX 基础宏包下载失败，请检查网络后重试")
    report("TeX 基础宏包已就绪")


def missing_files(log):
    """TeX files a failed offline build asked for and did not find."""
    found = []
    # TeX wraps its log at 79 columns, which splits file names and messages.
    log = re.sub(r"(?m)^(.{79})\n", r"\1", log)
    for match in MISSING.finditer(log):
        name = next(group for group in match.groups() if group)
        if match[4]:  # xdvipdfmx found the metrics but no virtual font or outline
            name += ".vf"
        if name.startswith("["):  # an OpenType font requested by file name
            name = name.strip("[]")
            name = name if "." in name else name + ".otf"
        name = name if "." in name else name + ".tfm"
        if NAME.fullmatch(name) and name not in found:
            found.append(name)
    return found


def fetch(names, report=print):
    """Download the named TeX files (and what the packages among them load)."""
    names = [name for name in names if NAME.fullmatch(name)]
    if not names:
        return
    report("正在下载缺失的 TeX 文件：" + "、".join(names))
    probes = "\n".join(rf"\IfFileExists{{{name}}}{{}}{{}}" for name in names)
    run("\\documentclass{article}\n" + probes + "\n\\begin{document}x\\end{document}\n", report)
    for name in names:
        stem, _, kind = name.rpartition(".")
        if kind == "sty":
            run(document((stem,)), report)
        elif kind in ("otf", "ttf"):
            run("\\documentclass{article}\n\\begin{document}\n"
                rf'\font\probe="[{name}]" \probe x' "\n\\end{document}\n", report)
        elif kind == "cls":
            run(rf"\documentclass{{{stem}}}" "\n\\begin{document}x\\end{document}\n", report)
