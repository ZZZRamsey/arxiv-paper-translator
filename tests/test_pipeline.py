import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_translate.cli import enable_xetex_translation, main, patch_pdftex_styles
from paper_translate.sandbox import detect_engine
from paper_translate.source import check_download_url, extract, normalize
from paper_translate.translate import Translator, bilingual_title, mask, plan, restore
from paper_translate.verify import publish


class SourceTests(unittest.TestCase):
    def test_three_input_forms(self):
        for form in ("2503.09516", "https://arxiv.org/abs/2503.09516",
                     "https://arxiv.org/pdf/2503.09516.pdf?download=1"):
            self.assertEqual(normalize(form), "2503.09516")
        self.assertEqual(normalize("https://arxiv.org/abs/hep-th/9901001v2"), "hep-th/9901001v2")
        with self.assertRaises(ValueError):
            normalize("https://arxiv.org.example.com/abs/2503.09516")

    def test_unsafe_archives(self):
        for name, kind in (("../outside", tarfile.REGTYPE), ("main.tex", tarfile.SYMTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                data = io.BytesIO()
                with tarfile.open(fileobj=data, mode="w") as archive:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    entry.linkname = "outside"
                    archive.addfile(entry)
                target = Path(temp) / "source"
                with self.assertRaises(ValueError):
                    extract(data.getvalue(), target)
                self.assertFalse(target.exists())

    def test_redirect_must_keep_host_and_version(self):
        check_download_url("https://export.arxiv.org/src/2503.09516v5", "2503.09516v5")
        for url in ("https://localhost/src/2503.09516v5", "https://arxiv.org/src/2503.09516v4"):
            with self.assertRaises(ValueError):
                check_download_url(url, "2503.09516v5")


class TranslationTests(unittest.TestCase):
    def test_pdftex_guard_uses_pdftex_for_baseline_and_xetex_for_translation(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            root = source / "main.tex"
            style = source / "aaai.sty"
            root.write_text("\\documentclass{article}\n", encoding="utf-8")
            style.write_text("\\RequirePDFTeX\n", encoding="utf-8")
            self.assertEqual(detect_engine(source, root), "pdflatex")
            translated = enable_xetex_translation(root.read_text())
            root.write_text(translated, encoding="utf-8")
            changed = patch_pdftex_styles(source)
            self.assertEqual([path.name for path in changed], ["aaai.sty"])
            self.assertEqual(detect_engine(source, root), "tectonic")

    def test_bilingual_title_preserves_original_tex_and_short_title(self):
        original = "\\title[Short]{The \\emph{Original}}\n\\begin{document}"
        translated = "\\title[Short]{中文标题}\n\\begin{document}"
        self.assertEqual(bilingual_title(original, translated),
                         "\\title[Short]{{\\large 中文标题}\\\\[0.4ex]{\\Large The \\emph{Original}}}"
                         "\n\\begin{document}")

    def test_caption_translates_but_cell_is_opaque(self):
        tex = r"\begin{table}\caption{Results of \textbf{our model}}\begin{tabular}{c}Result\\\end{tabular}\end{table}"
        pieces = list(plan(tex))
        self.assertEqual("".join(piece for piece, _ in pieces), tex)
        self.assertEqual([piece for piece, active in pieces if active], [r"Results of \textbf{our model}"])

    def test_captionof_preserves_counter_and_translates_visible_text(self):
        tex = r"\captionof{figure}{Example over \num{6} runs.}"
        self.assertEqual([piece for piece, active in plan(tex, table=True) if active],
                         [r"Example over \num{6} runs."])

    def test_inserted_optional_argument_cannot_break_caption(self):
        masked, saved = mask(r"\caption{An example.}")
        self.assertEqual(restore("[[[T0]]][[[[T1]]]示例。[[[T2]]]", saved, masked),
                         r"\caption{示例。}")

    def test_dangling_bracket_copied_from_placeholder_is_removed(self):
        masked, saved = mask(r"~Data are available.")
        self.assertEqual(restore("[[[T0]]][数据可用。", saved, masked), r"~数据可用。")

    def test_restore_protects_math_and_citation(self):
        _, saved = mask(r"We set $x=1$ \cite{paper}.")
        self.assertEqual(restore("设置 [[[T0]]] [[[T1]]]。", saved), r"设置 $x=1$ \cite{paper}。")
        with self.assertRaises(ValueError):
            restore("设置 [[[T1]]]。", saved)

    def test_xetex_control_word_is_terminated(self):
        _, saved = mask(r"\Ours supports retrieval.")
        self.assertEqual(restore("[[[T0]]]支持检索。", saved), r"\Ours 支持检索。")

    def test_color_argument_is_opaque(self):
        masked, saved = mask(r"\textcolor{red}{question}")
        self.assertEqual(masked, "[[[T0]]][[[T1]]]question[[[T2]]]")
        self.assertEqual(restore("[[[T0]]][[[T1]]]问题[[[T2]]]", saved),
                         r"\textcolor{red}{问题}")

    def test_cache_separates_latex_context_and_recovers_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            translator = Translator("test", "test", Path(temp))
            first, second = "We use $x=1$.", "We use $y=2$."
            self.assertNotEqual(translator.cache_path(first), translator.cache_path(second))
            translator.cache_path(first).write_bytes(b"\xff")
            with patch.object(translator, "complete", return_value="使用 [[[T0]]]。") as complete:
                self.assertEqual(translator.translate(first), "使用 $x=1$。")
                self.assertEqual(translator.translate(first), "使用 $x=1$。")
                complete.assert_called_once()

    def test_batch_keeps_valid_results_and_retries_only_invalid_items(self):
        with tempfile.TemporaryDirectory() as temp:
            translator = Translator("test", "test", Path(temp))
            first, second = "First result.", "Second result."
            with patch.object(translator, "complete",
                              side_effect=['{"0":"第一项结果。","1":"invalid"}', "第二项结果。"]) as complete:
                self.assertEqual(translator.translate_batch([first, second]),
                                 {first: "第一项结果。", second: "第二项结果。"})
                self.assertEqual(complete.call_count, 2)

    def test_zero_request_budget_fails_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            translator = Translator("", "test", Path(temp), max_requests=0)
            with patch("requests.Session.post") as post:
                with self.assertRaises(RuntimeError):
                    translator.complete("test")
                post.assert_not_called()


class PublicationTests(unittest.TestCase):
    def test_public_defaults_ignore_local_key_and_output(self):
        with patch("sys.argv", ["arxiv-translate", "2503.09516",
                                "--public-defaults", "--max-requests", "0"]), \
                patch.dict("os.environ", {}, clear=True), \
                patch("paper_translate.cli.local_settings") as local, \
                patch("paper_translate.cli.run") as run:
            main()
            local.assert_not_called()
            args, key = run.call_args.args
            self.assertEqual(args.output, Path("output"))
            self.assertFalse(args.save_source)
            self.assertEqual(key, "")

    def test_copy_failure_does_not_expose_partial_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            target = work / "public"
            existing = work / "existing"
            existing.write_text("fixture")
            with self.assertRaises(FileNotFoundError):
                publish(target, work, {"pdf": existing, "zip": work / "missing"})
            self.assertFalse(target.exists())
