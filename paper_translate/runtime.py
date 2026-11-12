"""Where the program finds its own files: from source, installed, or inside the macOS app."""

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
APP_NAME = "arXiv Translator"


def tools_root():
    """Directory with bin/ and lib/ of the TeX and PDF tools shipped inside the app."""
    candidates = [os.getenv("ARXIV_TRANSLATOR_TOOLS")]
    if FROZEN:
        # <App>.app/Contents/Resources/backend/<executable> next to Resources/tools
        candidates.append(Path(sys.executable).resolve().parent.parent / "tools")
    for candidate in candidates:
        if candidate and (Path(candidate) / "bin").is_dir():
            return Path(candidate).resolve()
    return None


def cli_command(arguments):
    """Command line that runs one translation in a child process."""
    if FROZEN:
        return [sys.executable, "translate", *arguments]
    return [sys.executable, "-u", "-m", "paper_translate", *arguments]


def support_dir():
    path = Path.home() / "Library" / "Application Support" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_output():
    """The app has no meaningful working directory, so its output goes to Documents."""
    if FROZEN:
        return Path.home() / "Documents" / "arXiv 译文"
    return Path("output")
