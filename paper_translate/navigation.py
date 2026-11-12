"""Instrument hyperref/natbib citations and converge the printed page labels."""

import re
from collections import defaultdict

from pypdf import PdfReader

HOOK = r"""
\makeatletter
\newcount\APT@occ
\AtBeginDocument{%
  \@ifpackageloaded{natbib}{\@ifpackageloaded{hyperref}{%
    \hypersetup{colorlinks=true,citecolor=blue,linkcolor=blue}%
    \let\APT@oldanchor\hyper@natanchorstart
    \def\hyper@natanchorstart#1{%
      \gdef\APT@bibkey{#1}%
      \Hy@raisedlink{\hyper@anchorstart{ref-#1}\hyper@anchorend}%
      \APT@oldanchor{#1}%
    }%
    \def\hyper@natlinkstart#1{%
      \global\advance\APT@occ\@ne
      \Hy@raisedlink{\hyper@anchorstart{cite-\the\APT@occ-#1}\hyper@anchorend}%
      \hyper@linkstart{cite}{ref-#1}%
      \def\hyper@nat@current{#1}%
    }%
    \def\hyper@natlinkbreak#1#2{\hyper@linkend#1\hyper@linkstart{cite}{ref-#2}}%
    \let\APT@oldfin\bibitem@fin
    \def\bibitem@fin{%
      \APT@oldfin
      \ifdefined\APT@bibkey
        \@ifundefined{APT@back@\APT@bibkey}{}{%
          \par\noindent{\footnotesize\@nameuse{APT@back@\APT@bibkey}}\par
        }%
        \global\let\APT@bibkey\@undefined
      \fi
    }%
    \InputIfFileExists{apt-citation-returns.tex}{}{}%
  }{}}{}%
}
\makeatother
"""

OCCURRENCE = re.compile(r"cite-(\d+)-([A-Za-z0-9:._/@+-]+)\Z")
PAGE = re.compile(r"[A-Za-z0-9.-]+\Z")


def return_source(path):
    document = PdfReader(path)
    found = defaultdict(list)
    destinations = document.named_destinations
    page_labels = document.page_labels
    for name, destination in destinations.items():
        match = OCCURRENCE.fullmatch(name)
        if not match:
            if re.match(r"cite-\d+-", name):
                raise ValueError(f"不支持的 natbib 引用键：{name}")
            continue
        index = document.get_destination_page_number(destination)
        if not isinstance(index, int) or not 0 <= index < len(document.pages):
            raise ValueError(f"无法定位正文引用：{name}")
        key = match[2]
        if "ref-" + key not in destinations:
            raise ValueError(f"找不到文献条目：{key}")
        label = page_labels[index]
        if not PAGE.fullmatch(label):
            # Templates without printed page numbers (ACL styles) give an empty label.
            label = str(index + 1)
        found[key].append((int(match[1]), index, label, name))
    lines = []
    for key, items in sorted(found.items()):
        seen = defaultdict(int)
        totals = defaultdict(int)
        for _, index, _, _ in items:
            totals[index] += 1
        links = []
        for _, index, label, name in sorted(items):
            seen[index] += 1
            suffix = f"（{seen[index]}）" if totals[index] > 1 else ""
            links.append(r"\hyperlink{" + name + "}{返回正文第 " + label + " 页引用处" + suffix + "}")
        lines.append(r"\expandafter\def\csname APT@back@" + key + r"\endcsname{"
                     + r"\quad\allowbreak ".join(links) + "}")
    return "\n".join(lines) + "\n" if lines else ""


def build_with_returns(root, compile_once):
    returns = root.parent / "apt-citation-returns.tex"
    if returns.exists():
        raise ValueError("源码与保留文件 apt-citation-returns.tex 重名")
    previous = ""
    for attempt in range(5):
        print(f"中文编译与引用定位：第 {attempt + 1} 轮", flush=True)
        pdf, pages = compile_once()
        current = return_source(pdf)
        if current == previous:
            return pdf, pages
        returns.write_text(current, encoding="utf-8")
        previous = current
    raise ValueError("逐次引用的返回页码未在五次构建内收敛")
