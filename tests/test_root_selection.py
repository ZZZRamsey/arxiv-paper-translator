import tempfile
import unittest
from pathlib import Path
from paper_translate.cli import locate_root, root_candidates
from paper_translate.zotero import ZoteroLocal

class RootSelectionTests(unittest.TestCase):
    def test_main_default_and_explicit_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory).resolve()
            for name in ("main.tex", "bak/neurips_2025_bak.tex"):
                path = source / name
                path.parent.mkdir(exist_ok=True)
                path.write_text(r"\documentclass{article}\begin{document}Hello\end{document}")
            self.assertEqual(len(root_candidates(source)), 2)
            self.assertEqual(locate_root(source), source / "main.tex")
            self.assertEqual(locate_root(source, "bak/neurips_2025_bak.tex"), source / "bak/neurips_2025_bak.tex")
            (source / "main.tex").rename(source / "other.tex")
            with self.assertRaisesRegex(ValueError, "候选"):
                locate_root(source)
            with self.assertRaises(ValueError):
                locate_root(source, "../outside.tex")

    def test_only_translated_attachments_are_replaceable(self):
        for filename in ("paper.pdf", "2601.13719.pdf", "paper_zh_CN_notes.txt"):
            self.assertFalse(ZoteroLocal._is_translation({"itemType": "attachment", "filename": filename, "title": "English original"}))
        self.assertTrue(ZoteroLocal._is_translation({"itemType": "attachment", "filename": "2601.13719_zh_CN_HAVEN.pdf"}))
        self.assertTrue(ZoteroLocal._is_translation({"itemType": "attachment", "title": "论文 中文译本"}))
        self.assertFalse(ZoteroLocal._is_translation({"itemType": "attachment", "title": "论文 中文译本", "deleted": True}))
