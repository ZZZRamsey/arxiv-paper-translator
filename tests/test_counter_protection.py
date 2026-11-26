import unittest
import tempfile
from pathlib import Path
from paper_translate.translate import validate_structure, Translator
from paper_translate.cli import repair_model_tex
from paper_translate.translate import OPAQUE, mask
from paper_translate.fonts import FONT_FILE, ensure_cjk_font
from paper_translate.zotero import ZoteroLocal

class CounterProtectionTests(unittest.TestCase):
    def test_unbraced_command_definition_is_opaque(self):
        source = r'\renewcommand\thesubsection{\Alph{section}.\arabic{subsection}}'
        self.assertIsNotNone(OPAQUE.fullmatch(source))
        masked, saved = mask(source)
        self.assertNotIn('section', masked)
        self.assertEqual(saved, [source])

    def test_generic_command_optional_arguments_are_opaque(self):
        source = r'\makebox[\linewidth][c]{Caption}'
        masked, saved = mask(source)
        self.assertEqual(masked, '[[[T0]]][[[T1]]]Caption[[[T2]]]')
        self.assertEqual(saved, [r'\makebox[\linewidth][c]', '{', '}'])

    def test_multiline_graphic_options_and_paths_are_opaque(self):
        source = r'''\includegraphics[
    width=0.32\textwidth
]{asset/point/point1.pdf}'''
        masked, saved = mask(source)
        self.assertEqual(masked, '[[[T0]]]')
        self.assertEqual(saved, [source])

    def test_restore_cached_counter_names_without_changing_prose(self):
        original = r'\Alph{section}.\arabic{subsection}\section{APPENDIX}'
        translated = r'\Alph{章节}.\arabic{子章节}\section{附录}'
        self.assertEqual(repair_model_tex(translated, original),
                         r'\Alph{section}.\arabic{subsection}\section{附录}')

    def test_structure_rejects_corrupted_or_missing_macros(self):
        original = r'\renewcommand\thesection{\Alph{section}}'
        for corrupt in (r'\renewcommand\thesection{\Alph{章节}}', ''):
            with self.assertRaises(ValueError):
                validate_structure(original, corrupt)
        validate_structure(original + r'\section{Appendix}', original + r'\section{附录}')

    def test_bad_local_cache_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Translator('', 'test', Path(directory), max_requests=0, local='http://localhost:11434')
            source = r'Section \Alph{section} describes the method.'
            model.cache_path(source).write_text(r'第 \Alph{章节} 节介绍方法。')
            with self.assertRaises(RuntimeError):
                model.translate_local(source)
            self.assertEqual(model.hits, 0)

    def test_zotero_does_not_match_empty_note_title(self):
        from paper_translate.zotero import ZoteroLocal
        self.assertFalse(ZoteroLocal._matches({'data': {'itemType': 'note'}}, '2504.14904', ''))
        self.assertFalse(ZoteroLocal._matches({'data': {'itemType': 'note', 'title': '2504.14904'}}, '2504.14904', ''))
        self.assertTrue(ZoteroLocal._matches({'data': {'itemType': 'preprint', 'url': 'https://arxiv.org/abs/2504.14904'}}, '2504.14904', ''))

    def test_zotero_arxiv_match_is_exact(self):
        self.assertTrue(ZoteroLocal._matches({'data': {'itemType': 'preprint', 'extra': 'arXiv:2605.27365v2'}}, '2605.27365', ''))
        self.assertFalse(ZoteroLocal._matches({'data': {'itemType': 'preprint', 'extra': 'arXiv:12605.27365'}}, '2605.27365', ''))
        self.assertFalse(ZoteroLocal._matches({'data': {'itemType': 'preprint', 'title': '2605.27365'}}, '2605.27365', ''))

    def test_missing_font_reports_and_uses_downloaded_fallback(self):
        messages = []
        self.assertEqual(ensure_cjk_font('Definitely Missing Font', messages.append), str(FONT_FILE))
        self.assertTrue(any('未找到' in message for message in messages))

    def test_unicode_compilation_uses_path_font_and_disables_microtype_tracking(self):
        from paper_translate.cli import configure_chinese
        result = configure_chinese("\\documentclass{article}\n\\begin{document}测试\\end{document}", 'Songti SC')
        self.assertIn('Extension=.ttc,FontIndex=0', result)
        self.assertIn('\\microtypesetup{protrusion=false,expansion=false,tracking=false}', result)
