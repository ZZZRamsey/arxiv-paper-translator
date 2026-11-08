"""Download, translate, build and package a versioned arXiv manuscript."""

import argparse
import getpass
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tarfile
import zipfile
from pathlib import Path

import requests
from pypdf.errors import PdfReadError

from .source import digest, extract, fetch, lock_version, normalize, validate_pdf
from .sandbox import command_for, detect_engine
from .navigation import HOOK, build_with_returns
from .translate import DEFAULT_MODEL, Translator, bilingual_title, title_content
from .verify import check_titles, direct_links, inspect_pdf, render_hashes, verify_bibliography
from .settings import local_settings

COMMENT = re.compile(r"(?<!\\)%[^\n]*")
INPUT = re.compile(r"\\(?:input|include|subfile)(?![A-Za-z@])\s*(?:\{([^{}]+)\}|([^\s%{}\\]+))")


def locate_root(source, override=None):
    candidates = []
    for path in sorted(source.rglob("*.tex")):
        text = COMMENT.sub("", path.read_text(encoding="utf-8-sig", errors="replace"))
        if re.search(r"\\document(?:class|style)\b", text) and r"\begin{document}" in text:
            candidates.append(path)
    if override:
        path = (source / override).resolve()
        if path not in candidates:
            raise ValueError("--root 必须指定源码包内的文档根 TeX")
        return path
    readme = source / "00README.json"
    if readme.is_file():
        data = json.loads(readme.read_text(encoding="utf-8"))
        hints = {entry.get("filename") for entry in data.get("sources", [])
                 if entry.get("usage") == "toplevel"}
        selected = [p for p in candidates if p.relative_to(source).as_posix() in hints]
        if len(selected) == 1:
            return selected[0]
    if len(candidates) != 1:
        names = ", ".join(str(p.relative_to(source)) for p in candidates)
        raise ValueError(f"无法唯一确定根 TeX，可用 --root 指定。候选：{names or '无'}")
    return candidates[0]


def input_tree(root, source):
    documents = {}
    visited = set()
    pending = [(root, False)]
    while pending:
        path, protected = pending.pop()
        if (path, protected) in visited:
            continue
        visited.add((path, protected))
        text = path.read_text(encoding="utf-8-sig")
        clean = COMMENT.sub("", text)
        # Included table files can consist of a naked tabular fragment.
        table = path != root and (
            any(part.lower() in ("tables", "table", "appx_tables", "figures", "trajectories")
                for part in path.relative_to(source).parts[:-1])
            or bool(re.match(r"\s*\\begin\{(?:tabular|longtable)", clean))
        )
        if not protected:
            documents[path] = (text, path == root, table)
        preamble_end = clean.find(r"\begin{document}") if path == root else -1
        for match in INPUT.finditer(clean):
            braced, bare = match.groups()
            name = braced or bare
            choices = (name, name + ".tex")
            for parent in (root.parent, path.parent):
                found = [(parent / choice).resolve() for choice in choices]
                found = [target for target in found if target.is_relative_to(source) and target.is_file()]
                if found:
                    pending.append((found[0], protected or match.start() < preamble_end))
                    break
            else:
                raise ValueError(f"无法解析 TeX 输入 {name!r}（{path.relative_to(source)}）")
    return documents


def build(root, target, log, source=None, engine=None):
    target.mkdir(exist_ok=True, parents=True)
    source = source or root.parent
    engine = engine or detect_engine(source, root)
    if engine == "tectonic":
        engine_args = ["--keep-logs", "--outdir", str(target), "--", root.name]
        working_directory = root.parent
    elif engine == "pdflatex":
        engine_args = ["-interaction=nonstopmode", "-halt-on-error", "-file-line-error",
                       "-output-directory", str(target), root.name]
        working_directory = root.parent
    else:
        raise ValueError(f"不支持的 TeX 编译引擎：{engine}")
    with log.open("w", encoding="utf-8") as stream:
        passes = 1 if engine == "tectonic" else 3
        result = None
        for attempt in range(passes):
            command, environment = command_for(source, target, engine_args, engine=engine)
            stream.write(f"\n=== {engine} pass {attempt + 1} ===\n")
            result = subprocess.run(command, cwd=working_directory, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=360, env=environment)
            if result.returncode:
                break
        if result and result.returncode == 0 and engine == "pdflatex":
            aux = target / f"{root.stem}.aux"
            if aux.is_file() and r"\bibdata" in aux.read_text(encoding="utf-8", errors="replace"):
                command, environment = command_for(source, target, [root.stem], engine="bibtex")
                environment["BIBINPUTS"] = f"{root.parent}:{target}:"
                stream.write("\n=== bibtex ===\n")
                result = subprocess.run(command, cwd=target, stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=360, env=environment)
                if result.returncode == 0:
                    for attempt in range(2):
                        command, environment = command_for(source, target, engine_args, engine=engine)
                        stream.write(f"\n=== {engine} bibliography pass {attempt + 1} ===\n")
                        result = subprocess.run(command, cwd=working_directory, stdout=stream,
                                                stderr=subprocess.STDOUT, timeout=360, env=environment)
                        if result.returncode:
                            break
    pdf = target / (root.stem + ".pdf")
    output = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in [log, *target.glob("*.log")]
        if path.is_file()
    )
    if ("PDFLaTeX is required" in output or "pdfTeX is required" in output
            or "terminal input forbidden" in output):
        raise ValueError(
            "源码强制要求 PDFLaTeX，但当前环境只有 Tectonic/XeTeX。"
            "请安装 PDFLaTeX（例如 BasicTeX/MacTeX）后重试，或使用支持 XeTeX 的源码版本。"
        )
    if result.returncode or not pdf.is_file():
        raise ValueError(f"LaTeX 编译失败，日志：{log}")
    if "errors were issued by BibTeX" in output:
        raise ValueError(f"BibTeX 构建失败（PDF 可能缺少参考文献），日志：{log}")
    return pdf, validate_pdf(pdf.read_bytes())


def checksum_tree(root):
    return {path.relative_to(root).as_posix(): digest(path.read_bytes())
            for path in sorted(root.rglob("*")) if path.is_file()}


def add_local_dependencies(directory, root):
    if not directory:
        return {}
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("本地 TeX 依赖必须是目录")
    paths = sorted(directory.rglob("*"))
    if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in paths):
        raise ValueError("本地 TeX 依赖目录只能包含普通文件和目录")
    files = [(p, p.relative_to(directory)) for p in paths if p.is_file()]
    if any((root / relative).exists() for _, relative in files):
        raise ValueError("本地 TeX 依赖与论文源码文件重名")
    for source, relative in files:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return {relative.as_posix(): digest(source.read_bytes()) for source, relative in files}


def configure_chinese(tex, font):
    if not re.fullmatch(r"[\w .-]+", font):
        raise ValueError("无效的中文字体名称")
    tex = re.sub(r"(?m)^([ \t]*)\\linenumbers\b(?:\[[^\]\n]*\])?", r"\1", tex)
    if re.search(r"\\usepackage(?:\[[^\]]*\])?\{xeCJK\}", COMMENT.sub("", tex)):
        package = ""
    else:
        package = "\\usepackage{xeCJK}\n"
    # The legacy Times package selects 8-bit fonts that drop Unicode characters
    # in references, code examples and prose under XeTeX.
    legacy_times = re.search(r"(?m)^[ \t]*\\usepackage\{times\}", tex)
    if legacy_times:
        tex = re.sub(r"(?m)^[ \t]*\\usepackage(?:\[[^\]\n]*\])?\{(?:times|fontenc|inputenc)\}",
                     "", tex)
        package += (
            "\\setmainfont{Times New Roman}\n"
            "\\setsansfont{Arial}\n"
            "\\setmonofont{Courier New}\n"
        )
    preamble = package + "".join(f"\\setCJK{family}font{{{font}}}\n"
                                 for family in ("main", "sans", "mono"))
    return re.sub(r"(?m)^[ \t]*\\begin\{document\}", lambda m: preamble + m[0], tex, count=1)


def enable_xetex_translation(tex):
    """Allow a PDFLaTeX-only style to load in the Unicode translation build."""
    if "ARXIV_TRANSLATOR_XETEX" in tex:
        return tex
    return (
        "% ARXIV_TRANSLATOR_XETEX\n"
        "\\PassOptionsToPackage{table}{xcolor}\n"
        "\\def\\pdfinfo#1{}\n"
        "\\newdimen\\pdfpagewidth\n"
        "\\newdimen\\pdfpageheight\n"
        + tex
    )


def patch_pdftex_styles(root):
    """Disable a PDFLaTeX guard in the private Unicode build copy."""
    changed = []
    for path in sorted(root.rglob("*.sty")):
        text = path.read_text(encoding="utf-8", errors="replace")
        patched = text.replace(
            r"\RequirePDFTeX",
            "% PDFLaTeX guard disabled for the Unicode translation build",
        )
        if patched != text:
            path.write_text(patched, encoding="utf-8")
            changed.append(path)
    return changed


def run(args, key):
    started = time.monotonic()
    if sys.platform != "darwin" or not (shutil.which("tectonic") or shutil.which("pdflatex")
                                         or Path("/Library/TeX/texbin/pdflatex").is_file()):
        raise ValueError("隔离编译需要 macOS，并安装 Tectonic 或 BasicTeX/MacTeX")
    renderer = args.pdftoppm or shutil.which("pdftoppm")
    if not renderer or not os.access(renderer, os.X_OK):
        raise ValueError("需要可运行的 Poppler pdftoppm，可用 --pdftoppm 指定")
    renderer = Path(renderer).resolve()
    print("正在解析 arXiv 输入并锁定版本", flush=True)
    identifier = normalize(args.paper)
    version, lookup = lock_version(identifier)
    stem = re.sub(r"v\d+$", "", version).replace("/", "_") + "_zh_CN"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / (stem + ".pdf")
    zip_destination = output / (stem + "_latex.zip")
    if destination.exists() or (args.save_source and zip_destination.exists()):
        raise ValueError(f"输出文件已存在：{destination}")
    work_root = output / ".arxiv-work"
    work_root.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{version.replace('/', '_')}-", dir=work_root))
    print(f"锁定 {version}，工作目录 {work}", flush=True)
    print("正在下载同版本 PDF 和 LaTeX 源码", flush=True)
    pdf_bytes, pdf_meta = fetch("pdf", version)
    original_pages = validate_pdf(pdf_bytes)
    (work / "original.pdf").write_bytes(pdf_bytes)
    original = work / "original-source"
    errors = []
    for route in ("src", "e-print"):
        try:
            data, source_meta = fetch(route, version)
            (work / f"{route}.download").write_bytes(data)
            with tempfile.TemporaryDirectory(dir=work) as directory:
                extracted = Path(directory) / "source"
                extract(data, extracted)
                extracted.rename(original)
            break
        except (requests.RequestException, OSError, ValueError, EOFError,
                tarfile.TarError, zipfile.BadZipFile) as error:
            errors.append(f"{route}: {error}")
    else:
        raise ValueError("无法获取可用的 LaTeX 源码：" + "；".join(errors))
    root = locate_root(original, args.root)
    title_content(root.read_text(encoding="utf-8-sig"))
    relative_root = root.relative_to(original)
    original_files = checksum_tree(original)
    if args.tex_overlay:
        build_source = work / "build-source"
        shutil.copytree(original, build_source)
        dependencies = add_local_dependencies(args.tex_overlay, (build_source / relative_root).parent)
        print(f"已加载 {len(dependencies)} 个本地 TeX 依赖文件", flush=True)
    else:
        build_source, dependencies = original, {}
    print(f"英文基线编译：{relative_root}", flush=True)
    baseline_engine = detect_engine(build_source, build_source / relative_root)
    baseline, baseline_pages = build(build_source / relative_root, work / "baseline",
                                     work / "baseline.log", build_source, baseline_engine)
    download_and_baseline_seconds = round(time.monotonic() - started, 3)

    translated = work / "translated-source"
    shutil.copytree(build_source, translated)
    reserved = ("BUILD.txt", "provenance.json", "SHA256SUMS",
                "translation-audit.json", "postprocess_pdf.py")
    if any((translated / name).exists() for name in reserved):
        raise ValueError("arXiv 源码占用了交付元数据的保留文件名")
    documents = input_tree(root, original)
    if not documents:
        raise ValueError("未找到可翻译的文档")
    translator = Translator(key, args.model, output / ".translation-cache", args.max_requests)
    translation_start = time.monotonic()
    translations = translator.translate_all(documents, args.jobs)
    translation_seconds = round(time.monotonic() - translation_start, 3)
    original_title_bounds = title_content(documents[root][0])
    translated_title_bounds = title_content(translations[root])
    original_title = documents[root][0][slice(*original_title_bounds)].strip()
    translated_title = translations[root][slice(*translated_title_bounds)].strip()
    for path, content in translations.items():
        if path == root:
            content = bilingual_title(documents[path][0], content)
            content = configure_chinese(content, args.font)
            if baseline_engine == "pdflatex":
                content = enable_xetex_translation(content)
            content = re.sub(r"(?m)^[ \t]*\\begin\{document\}",
                             lambda match: HOOK + match[0], content, count=1)
        (translated / path.relative_to(original)).write_text(content, encoding="utf-8")
    edited = {path.relative_to(original).as_posix() for path in translations}
    compatibility_patches = []
    if baseline_engine == "pdflatex":
        compatibility_patches = patch_pdftex_styles(translated)
        edited.update(path.relative_to(original).as_posix() for path in compatibility_patches)
    for name, checksum in original_files.items():
        if name not in edited and digest((translated / name).read_bytes()) != checksum:
            raise ValueError(f"未经翻译的源码或资源发生变动：{name}")
    print("中文编译", flush=True)
    translation_engine = "tectonic" if baseline_engine == "pdflatex" else baseline_engine
    pdf, pages = build_with_returns(
        translated / relative_root,
        lambda: build(translated / relative_root, work / "compiled", work / "chinese.log",
                      translated, translation_engine),
    )
    navigation = direct_links(pdf)
    titles = check_titles(pdf, original_title, translated_title)
    bibliography_entries = verify_bibliography(baseline, pdf)
    compile_log = pdf.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
    if re.search(r"Missing character:|There were undefined (?:references|citations)", compile_log):
        raise ValueError(f"中文编译存在缺字或未解析引用，日志：{pdf.with_suffix('.log')}")
    print(f"中文 PDF 已编译：{pages} 页；正在核验引用和独立重建", flush=True)
    original_inspection = inspect_pdf(work / "original.pdf")
    inspection = inspect_pdf(pdf)
    findings = []
    if original_inspection["geometry"] != inspection["geometry"]:
        findings.append("中文 PDF 的分页或页面尺寸与原版不同")
    if not all(navigation["links"].values()):
        findings.append("缺少 skill 要求的逐次双向引用导航")
    if not inspection["han_characters"]:
        findings.append("PDF 中无法提取中文文字")
    # Structure and pixel checks do not establish semantic or layout equivalence.
    findings.append("逐块语义覆盖和逐页视觉验收仍需人工复核")
    info = {
        "input": args.paper, "version": version, "lookup": lookup, "pdf": pdf_meta,
        "source": source_meta, "source_attempt_errors": errors, "model": args.model,
        "compiler": {"baseline": baseline_engine, "translation": translation_engine},
        "font": args.font, "root": relative_root.as_posix(),
        "pages": {"arxiv": original_pages, "baseline": baseline_pages, "translation": pages},
        "translated_files": [p.relative_to(original).as_posix() for p in translations],
        "compatibility_patches": [p.relative_to(translated).as_posix()
                                  for p in compatibility_patches],
        "original_files": original_files, "local_tex_dependencies": dependencies,
        "baseline_sha256": digest(baseline.read_bytes()),
        "translation_sha256": digest(pdf.read_bytes()),
        "navigation": navigation, "findings": findings,
        "titles": {"original": original_title, "translated": translated_title, "checks": titles},
        "bibliography_entries": bibliography_entries,
        "requests": translator.requests, "cache_hits": translator.hits,
        "openrouter_reported_usage": translator.usage,
        "seconds": {"download_and_baseline": download_and_baseline_seconds,
                    "translation": translation_seconds},
    }
    audit = {Path(path).relative_to(original).as_posix(): blocks
             for path, blocks in translator.audit.items()}
    (translated / "translation-audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (translated / "provenance.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    (translated / "BUILD.txt").write_text(
        f"Requires {translation_engine} and the CJK font {args.font}.\n"
        "Build only in an isolated environment with trusted cached packages.\n"
        f"From {relative_root.parent}, run: {translation_engine} -- "
        f"{shlex.quote(relative_root.name)}\n"
        "Then run the bundled postprocess_pdf.py (requires pypdf>=5,<7) on a PDF copy.\n",
        encoding="utf-8",
    )
    shutil.copyfile(Path(__file__).with_name("verify.py"), translated / "postprocess_pdf.py")
    (translated / "SHA256SUMS").write_text(
        "".join(f"{value}  {name}\n" for name, value in checksum_tree(translated).items()), encoding="utf-8"
    )
    independent = work / "independent"
    archive = None
    if args.save_source:
        archive = Path(shutil.make_archive(str(work / "latex"), "zip", translated))
        extract(archive.read_bytes(), independent)
    else:
        shutil.copytree(translated, independent)
    print("从独立目录重建并逐页比较", flush=True)
    if checksum_tree(independent) != checksum_tree(translated):
        raise ValueError("ZIP 独立解压后哈希不匹配")
    rebuilt, rebuilt_pages = build(independent / relative_root, work / "rebuilt",
                                   work / "rebuild.log", independent, translation_engine)
    if rebuilt_pages != pages:
        raise ValueError("独立构建页数与中文 PDF 不一致")
    if direct_links(rebuilt) != navigation:
        raise ValueError("独立构建的引用结构不一致")
    compiled_renders = render_hashes(pdf, work / "render", renderer)
    rebuilt_renders = render_hashes(rebuilt, work / "rebuilt-render", renderer)
    if len(compiled_renders) != pages or compiled_renders != rebuilt_renders:
        raise ValueError("独立构建的逐页渲染与中文 PDF 不一致")
    report = work / "verification.json"
    report.write_text(json.dumps({
        "status": "needs-review", "findings": findings, "pages": inspection,
        "titles": titles, "navigation": navigation["links"], "bibliography_entries": bibliography_entries,
        "render_sha256": compiled_renders, "total_seconds": round(time.monotonic() - started, 3),
        "pdf_sha256": digest(pdf.read_bytes()),
        **({"zip_sha256": digest(archive.read_bytes())} if archive else {}),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.strict:
        raise ValueError(f"验收未通过，产物保留在工作目录。报告：{report}")
    print(f"自动核验完成，待复核事项：{'；'.join(findings)}", flush=True)
    print(f"验收报告：{report}", flush=True)
    if archive:
        os.link(archive, zip_destination)
        try:
            os.link(pdf, destination)
        except OSError:
            zip_destination.unlink()
            raise
    else:
        os.link(pdf, destination)
    print(f"PDF 已保存：{destination}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="使用 OpenRouter 翻译 arXiv LaTeX 源码")
    parser.add_argument("paper", help="arXiv 编号或 abs/pdf URL")
    parser.add_argument("--model", default=os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--root", help="根 TeX 在 arXiv 源码包中的相对路径")
    parser.add_argument("--font", default="Songti SC")
    parser.add_argument("--jobs", type=int, choices=range(1, 9), default=4, metavar="1-8")
    parser.add_argument("--max-requests", type=int, default=500)
    parser.add_argument("--pdftoppm", type=Path, help="Poppler pdftoppm 路径")
    parser.add_argument("--tex-overlay", type=Path, help="可信的本地 TeX 依赖目录，不覆盖原稿")
    parser.add_argument("--save-source", action="store_true", help="额外保存 LaTeX 源码 ZIP")
    parser.add_argument("--strict", action="store_true", help="人工复核未完成时保留工作产物，禁止发布")
    parser.add_argument("--public-defaults", action="store_true", help="忽略本机固定配置")
    args = parser.parse_args()
    try:
        if args.max_requests < 0:
            raise ValueError("--max-requests 不能小于 0")
        config = {} if args.public_defaults else local_settings()
        args.output = args.output or Path(config.get("output", "output"))
        if not args.pdftoppm and config.get("pdftoppm"):
            args.pdftoppm = Path(config["pdftoppm"])
        if not args.tex_overlay and config.get("tex_overlay"):
            args.tex_overlay = Path(config["tex_overlay"])
        if not args.tex_overlay and config.get("tex_overlays"):
            paper_id = re.sub(r"v\d+$", "", normalize(args.paper))
            overlay = config["tex_overlays"].get(paper_id)
            if overlay:
                args.tex_overlay = Path(overlay)
        key = os.getenv("OPENROUTER_API_KEY") or config.get("api_key")
        if not key and args.max_requests and sys.stdin.isatty():
            key = getpass.getpass("OpenRouter API key: ")
        if not key and args.max_requests:
            raise ValueError("请设置 OPENROUTER_API_KEY")
        run(args, key or "")
    except (ValueError, OSError, RuntimeError, PdfReadError, requests.RequestException,
            subprocess.SubprocessError) as error:
        parser.exit(1, f"错误：{error}\n")
