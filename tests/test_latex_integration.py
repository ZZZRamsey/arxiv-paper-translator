"""Exercise exact coordinates and the host sandbox when Tectonic is available."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from paper_translate.cli import build
from paper_translate.verify import direct_links


@unittest.skipUnless(
    sys.platform == "darwin" and shutil.which("tectonic")
    and (Path.home() / "Library/Caches/TectonicProject.Tectonic").is_dir(),
    "requires macOS with a warm Tectonic cache",
)
class LatexIntegration(unittest.TestCase):
    def test_sandbox_and_two_distinct_returns(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory).resolve()
            outside = work / "outside.txt"
            outside.write_text("sandbox fixture")
            source = work / "source"
            source.mkdir()
            root = source / "main.tex"
            root.write_text(
                r"""\documentclass{article}
\usepackage[colorlinks=true,linkcolor=blue]{hyperref}
\begin{document}
\newread\probe
\openin\probe=""" + '"' + str(outside) + '"' + r"""
\ifeof\probe\else\errmessage{Sandbox exposed an outside file}\fi
\closein\probe
\hypertarget{cite-fixture-one}{}\hyperlink{ref-fixture}{First reference.}
\par\vspace{10em}
\hypertarget{cite-fixture-two}{}\hyperlink{ref-fixture}{Second reference.}
\newpage
\vspace*{8em}
\hypertarget{ref-fixture}{}The reference entry.
\par\hyperlink{cite-fixture-one}{Return one.}
\par\hyperlink{cite-fixture-two}{Return two.}
\end{document}
""",
                encoding="utf-8",
            )
            pdf, pages = build(root, work / "out", work / "build.log", source)
            self.assertEqual(pages, 2)
            self.assertEqual(direct_links(pdf)["links"], {"ref-": 2, "cite-": 2})
            document = PdfReader(pdf)
            forward = [a.get_object()["/A"]["/D"] for a in document.pages[0]["/Annots"]]
            back = [a.get_object()["/A"]["/D"] for a in document.pages[1]["/Annots"]]
            self.assertEqual(forward[0], forward[1])
            self.assertEqual(forward[0][0].idnum, document.pages[1].indirect_reference.idnum)
            self.assertEqual(back[0][0].idnum, document.pages[0].indirect_reference.idnum)
            self.assertEqual(back[1][0].idnum, document.pages[0].indirect_reference.idnum)
            self.assertGreater(abs(back[0][3] - back[1][3]), 30)
            self.assertTrue(all(target[1] == "/XYZ" for target in forward + back))
