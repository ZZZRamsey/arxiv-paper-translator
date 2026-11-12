import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from paper_translate.cli import enable_xetex_translation, main, output_paths, patch_pdftex_styles
from paper_translate.sandbox import detect_engine
from paper_translate.source import check_download_url, extract, lock_version, normalize
from paper_translate.ollama import FIXED, ensure_server
from paper_translate.translate import tag_pairs, faithful, local_mask, Translator, bilingual_title, mask, plan, restore
from paper_translate.verify import publish


class SourceTests(unittest.TestCase):
    def test_three_input_forms(self):
        for form in ("2503.09516", "https://arxiv.org/abs/2503.09516",
                     "https://arxiv.org/pdf/2503.09516.pdf?download=1"):
            self.assertEqual(normalize(form), "2503.09516")
        self.assertEqual(normalize("https://arxiv.org/abs/hep-th/9901001v2"), "hep-th/9901001v2")
        with self.assertRaises(ValueError):
            normalize("https://arxiv.org.example.com/abs/2503.09516")

    def test_version_lookup_reads_title_and_abstract_from_same_page(self):
        page = (b'<meta property="og:title" content="A &amp; B">'
                b'<meta content="We introduce  Delta." property="og:description">'
                b'<strong>[v2]</strong>')
        with patch("paper_translate.source.fetch", return_value=(page, {})) as fetch:
            version, metadata = lock_version("2501.00001")
        fetch.assert_called_once_with("abs", "2501.00001")
        self.assertEqual((version, metadata["title"], metadata["abstract"]),
                         ("2501.00001v2", "A & B", "We introduce Delta."))

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
    def test_current_session_reads_answer_without_http(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            queue = root / "requests"
            model = Translator("", "current-session", root / "cache", chatgpt=queue)
            with patch("requests.Session.post", side_effect=AssertionError), ThreadPoolExecutor(1) as worker:
                pending = worker.submit(model.complete, "Translate this.")
                try:
                    deadline = time.monotonic() + 3
                    while not list(queue.glob("*.request.json")) and time.monotonic() < deadline:
                        time.sleep(0.01)
                    request, = queue.glob("*.request.json")
                    self.assertEqual(json.loads(request.read_text())[1]["content"], "Translate this.")
                    response = request.with_name(request.name.replace(".request.", ".response."))
                    temporary = response.with_suffix(".tmp")
                    temporary.write_text(json.dumps("中文译文"))
                    temporary.replace(response)
                    self.assertEqual(pending.result(timeout=3), "中文译文")
                finally:
                    model.stop.set()
            self.assertEqual(list(queue.iterdir()), [])

    def test_short_name_uses_both_fields_and_caches_validated_answer(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Translator("", "test", Path(temp))
            with patch.object(model, "complete", side_effect=[
                '{"name":"Invented"}', '{"name":"Delta-X"}', '{"name":null}'
            ]) as complete:
                self.assertEqual(model.short_name("Video reasoning", "We introduce Delta-X."), "Delta-X")
                request, = complete.call_args.args
                self.assertIn("Video reasoning", request)
                self.assertIn("We introduce Delta-X.", request)
                self.assertEqual(model.short_name("Video reasoning", "We introduce Delta-X."), "Delta-X")
                self.assertIsNone(model.short_name("Video reasoning", "A survey."))
                self.assertIsNone(model.short_name("Video reasoning", "A survey."))
                self.assertEqual(complete.call_count, 3)

    def test_short_name_is_appended_before_extension_as_one_component(self):
        root = Path("out")
        self.assertEqual(output_paths(root, "2501.00001v2", "Video-MTR"),
                         (root / "2501.00001_zh_CN_Video-MTR.pdf",
                          root / "2501.00001_zh_CN_latex_Video-MTR.zip"))
        self.assertEqual(output_paths(root, "hep-th/9901001v2", None)[0],
                         root / "hep-th_9901001_zh_CN.pdf")
        self.assertEqual(output_paths(root, "2501.00001v2", "Delta/XL")[0],
                         root / "2501.00001_zh_CN_Delta-XL.pdf")

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

    def test_formula_may_move_but_grouping_may_not(self):
        masked, saved = mask(r"It maximizes $r$ over rollouts from $\pi$ in \textbf{bold}.")
        self.assertEqual(
            restore("在从 [[[T1]]] 采样的轨迹上最大化 [[[T0]]]，见 [[[T2]]][[[T3]]]粗体[[[T4]]]。",
                    saved, masked),
            r"在从 $\pi$ 采样的轨迹上最大化 $r$，见 \textbf{粗体}。")
        with self.assertRaises(ValueError):
            restore("最大化 [[[T0]]] [[[T1]]] [[[T2]]][[[T4]]]粗体[[[T3]]]", saved, masked)
        with self.assertRaises(ValueError):
            restore("最大化 [[[T0]]] [[[T0]]] [[[T2]]][[[T3]]]粗体[[[T4]]]", saved, masked)

    def test_placeholder_with_lost_bracket_is_repaired(self):
        masked, saved = mask(r"See Table~\ref{tab:a}.")
        self.assertEqual(restore("见表[[[T0]][[[T1]]]。", saved, masked), r"见表~\ref{tab:a}。")

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


    def test_local_mask_merges_touching_placeholders_and_keeps_numbers(self):
        masked, saved = local_mask(r"We propose \textbf{Ours}, see Figure~\ref{f}. It gains 41\% on 7 sets.")
        self.assertEqual(masked, "We propose [[[T0]]]Ours[[[T1]]], see Figure[[[T2]]]. It gains 41% on 7 sets.")
        self.assertEqual(saved, ["\\textbf{", "}", "~\\ref{f}"])
        faithful(masked, "我们提出 [[[T0]]]Ours[[[T1]]]，见图[[[T2]]]。在 7 个数据集上提升 41%。")
        self.assertEqual(restore("我们提出 [[[T0]]]Ours[[[T1]]]，见图[[[T2]]]。在 7 个数据集上提升 41%。",
                                 saved, masked, tag_pairs(saved)),
                         "我们提出 \\textbf{Ours}，见图~\\ref{f}。在 7 个数据集上提升 41\\%。")
        with self.assertRaises(ValueError):
            faithful(masked, "我们提出 [[[T0]]]Ours[[[T1]]]，见图[[[T2]]]。在 7 个数据集上提升 14%。")
        with self.assertRaises(ValueError):
            faithful(masked, "我们提出 $[[[T0]]]Ours[[[T1]]]$，见图[[[T2]]]。在 7 个数据集上提升 41[[[T3]]]。")

    def test_local_retry_names_the_dropped_placeholder_then_goes_sentence_by_sentence(self):
        with tempfile.TemporaryDirectory() as temp:
            translator = Translator("", "test", Path(temp), local="http://127.0.0.1:11434")
            text = r"First point \cite{a}. Second point \cite{b}."
            answers = ["第一点和第二点 [[[T0]]]。"] * 3 + ["第一点 [[[T0]]]。", "第二点 [[[T1]]]。"]
            with patch.object(translator, "complete", side_effect=answers) as complete, \
                    patch.object(translator.stop, "wait", return_value=False):
                self.assertEqual(translator.translate(text), r"第一点 \cite{a}。 第二点 \cite{b}。")
                self.assertIn("left out [[[T1]]]", complete.call_args_list[1].kwargs["system"])
            with patch.object(translator, "complete") as complete:
                self.assertEqual(translator.translate(text), r"第一点 \cite{a}。 第二点 \cite{b}。")
                complete.assert_not_called()

    def test_ollama_restarts_only_when_settings_are_missing(self):
        good = {"OLLAMA_NUM_PARALLEL": "4", **FIXED}
        with patch("paper_translate.ollama.sys.platform", "darwin"), \
                patch("paper_translate.ollama.subprocess.run") as run, \
                patch("paper_translate.ollama.time.sleep"), \
                patch("paper_translate.ollama.requests.get") as get:
            with patch("paper_translate.ollama.server_settings", return_value=good):
                ensure_server("http://127.0.0.1:11434", 4)
                ensure_server("http://gpu-box:11434", 8)
            run.assert_not_called()
            with patch("paper_translate.ollama.server_settings", return_value={**good, "OLLAMA_NUM_PARALLEL": "1"}):
                ensure_server("http://127.0.0.1:11434", 4)
            self.assertIn(call(["launchctl", "setenv", "OLLAMA_NUM_PARALLEL", "4"], check=False),
                          run.call_args_list)
            get.assert_called()

    def test_whole_formatted_group_may_move_but_must_stay_nested(self):
        masked, saved = local_mask(r"\item We show \textbf{gains of 41\%} in setups (\textit{e.g.}, same data).")
        pairs = tag_pairs(saved)
        self.assertEqual(saved, ["\\item", "\\textbf{", "}", "\\textit{", "}"])
        self.assertEqual(pairs, {1: 2, 3: 4})
        moved = "[[[T0]]] 在相同设置（[[[T3]]]e.g.[[[T4]]]，相同数据）下，我们展示了[[[T1]]]提升 41%[[[T2]]]。"
        self.assertEqual(restore(moved, saved, masked, pairs),
                         r"\item 在相同设置（\textit{e.g.}，相同数据）下，我们展示了\textbf{提升 41\%}。")
        with self.assertRaises(ValueError):
            restore(moved, saved, masked)
        with self.assertRaises(ValueError):
            restore("[[[T0]]] 我们展示了[[[T1]]]提升 41%（[[[T3]]]e.g.[[[T2]]][[[T4]]]）。", saved, masked, pairs)

    def test_local_backend_calls_ollama_without_key(self):
        with tempfile.TemporaryDirectory() as temp:
            translator = Translator("", "qwen3.5:9b", Path(temp),
                                    local="http://127.0.0.1:11434")
            with patch("requests.Session.post") as post:
                post.return_value.ok = True
                post.return_value.status_code = 200
                post.return_value.json.return_value = {
                    "message": {"content": " 本地译文。 "}, "done_reason": "stop",
                    "prompt_eval_count": 7, "eval_count": 3,
                }
                self.assertEqual(translator.complete("Local text."), "本地译文。")
                (url,), options = post.call_args
                self.assertEqual(url, "http://127.0.0.1:11434/api/chat")
                self.assertNotIn("headers", options)
                self.assertIs(options["json"]["think"], False)
                self.assertEqual(translator.usage,
                                 {"prompt_tokens": 7, "completion_tokens": 3})
                post.return_value.json.return_value["done_reason"] = "length"
                with self.assertRaises(ValueError):
                    translator.complete("Local text.")


class PublicationTests(unittest.TestCase):
    def test_local_flag_needs_no_key(self):
        with patch("sys.argv", ["arxiv-translate", "2503.09516", "--public-defaults", "--local"]), \
                patch.dict("os.environ", {}, clear=True), \
                patch("paper_translate.cli.run") as run:
            main()
            args, key = run.call_args.args
            self.assertEqual((args.local, args.model, args.jobs, key),
                             ("http://127.0.0.1:11434", "qwen3.5:9b", 4, ""))

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
