import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_translate import runtime, settings, texcache
from paper_translate.sandbox import find_executable


class PackagingTests(unittest.TestCase):
    def test_missing_tex_files_are_read_from_a_failed_log(self):
        log = ("! LaTeX Error: File `lettrine.sty' not found.\n"
               "! I can't find file `cvpr.cls'.\n"
               "! LaTeX Error: File `../../etc/passwd' not found.\n"
               "! LaTeX Error: File `lettrine.sty' not found.\n")
        self.assertEqual(texcache.missing_files(log), ["lettrine.sty", "cvpr.cls"])
        wrapped = ("! Font TU/ppl/m/n/14.4=[lmroman12-regular]:mapping=tex-text; at 14.4pt not load\n"
                   "able: Metric (TFM) file or installed font not found.\n"
                   "! Font OT1/ptm/m/n/10=ptmr7t at 10.0pt not loadable: Metric (TFM) file not found.\n")
        self.assertEqual(len("! Font TU/ppl/m/n/14.4=[lmroman12-regular]:mapping=tex-text; at 14.4pt not load"), 79)
        self.assertEqual(texcache.missing_files(wrapped), ["lmroman12-regular.otf", "ptmr7t.tfm"])
        dvipdfmx = ('warning: Tectonic unable to generate PK font "cmr8.pfb" (dpi 600) on-the-fly\n'
                    "warning: >> Please check if kpathsea library can find this font: cmr8.pfb\n")
        self.assertEqual(texcache.missing_files(dvipdfmx), ["cmr8.pfb"])
        self.assertEqual(texcache.missing_files('warning: Could not locate a virtual/physical font for TFM "ptmb".\n'),
                         ["ptmb.vf"])
        self.assertEqual(texcache.missing_files('caused by: Unable to find TFM file "ptmb8r".\n'), ["ptmb8r.tfm"])

    def test_generated_fetch_document_only_names_packages(self):
        self.assertIn(r"\usepackage{xeCJK}", texcache.document(("xeCJK",)))
        with patch.object(texcache, "run") as run:
            texcache.fetch(["ok.sty", "bad name.sty", r"\input{x}.sty"], report=lambda line: None)
        self.assertTrue(all("bad name" not in call.args[0] and "input" not in call.args[0]
                            for call in run.call_args_list))
        self.assertEqual(len(run.call_args_list), 2)  # one probe, one package load

    def test_setup_panel_saves_openai_endpoint_and_default_engine(self):
        from paper_translate import web
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "local.json"
            clean = {k: v for k, v in os.environ.items() if not k.startswith("OPENAI_")}
            with patch.object(settings, "CONFIG", path), patch.dict(os.environ, clean, clear=True), \
                    patch.object(web, "describe", lambda: {}):
                web.save_settings({"engine": "openai", "openai_api_key": " k ",
                                   "openai_base_url": "http://127.0.0.1:8000/v1/", "openai_model": "served"})
                saved = settings.local_settings()
                self.assertEqual((saved["openai"], saved["local"], saved["openai_api_key"]), (True, False, "k"))
                self.assertEqual(saved["openai_base_url"], "http://127.0.0.1:8000/v1")
                web.save_settings({"engine": "local", "openai_base_url": ""})
                saved = settings.local_settings()
                self.assertNotIn("openai", saved)
                self.assertNotIn("openai_base_url", saved)
                self.assertTrue(saved["local"])
                with self.assertRaises(ValueError):
                    web.save_settings({"openai_base_url": "ftp://example"})

    def test_settings_update_keeps_other_keys_and_private_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "local.json"
            with patch.object(settings, "CONFIG", path):
                settings.update_settings({"api_key": "k", "local": True})
                settings.update_settings({"output": "/tmp/out", "api_key": None})
                self.assertEqual(json.loads(path.read_text()), {"local": True, "output": "/tmp/out"})
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(settings.local_settings()["output"], "/tmp/out")

    def test_bundled_tools_win_over_the_system_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            tool = Path(temp) / "bin" / "tectonic"
            tool.parent.mkdir()
            tool.write_text("#!/bin/sh\n")
            tool.chmod(0o755)
            with patch.dict("os.environ", {"ARXIV_TRANSLATOR_TOOLS": temp}):
                self.assertEqual(runtime.tools_root(), Path(temp).resolve())
                self.assertEqual(find_executable("tectonic").resolve(), tool.resolve())

    def test_setup_commands_are_not_translated(self):
        from paper_translate.translate import mask
        masked, saved = mask(r"\captionsetup{type=figure} A \definecolor{mygreen}{rgb}{0,0.6,0} caption.")
        self.assertEqual(masked, "[[[T0]]] A [[[T1]]] caption.")
        self.assertEqual(saved, [r"\captionsetup{type=figure}", r"\definecolor{mygreen}{rgb}{0,0.6,0}"])

    def test_pdftex_idioms_are_neutralized_for_xetex(self):
        from paper_translate.cli import xetex_compatible
        source = "\\pdfoutput=1\n\\documentclass{article}\n\\usepackage[accsupp]{axessibility}\n"
        result = xetex_compatible(source)
        self.assertIn("% \\pdfoutput=1", result)
        self.assertEqual(xetex_compatible("\\usepackage[pdftex, final]{graphicx}"), "\\usepackage[ final]{graphicx}")
        self.assertEqual(xetex_compatible("\\usepackage[pdftex]{graphicx}"), "\\usepackage[]{graphicx}")
        self.assertEqual(xetex_compatible("\\includegraphics[width=360px, height=2.5px]{a.pdf} 12px wide"),
                         "\\includegraphics[width=360bp, height=2.5bp]{a.pdf} 12bp wide")
        self.assertEqual(texcache.missing_files("warning: Could not read encoding file: cm-super-t1.enc\n"),
                         ["cm-super-t1.enc"])
        self.assertIn(r"\let\pdfcompresslevel\aptPDFsetting", result)
        self.assertEqual(xetex_compatible("\\documentclass{article}\n"), "\\documentclass{article}\n")

    def test_translation_command_differs_inside_the_app(self):
        self.assertEqual(runtime.cli_command(["x"])[1:], ["-u", "-m", "paper_translate", "x"])
        with patch.object(runtime, "FROZEN", True):
            self.assertEqual(runtime.cli_command(["x"])[1:], ["translate", "x"])


if __name__ == "__main__":
    unittest.main()
