"""Independent PDF and publication checks."""

import hashlib
import math
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, FloatObject, NameObject


def inspect_pdf(path):
    reader = PdfReader(path)
    return {
        "pages": len(reader.pages),
        "geometry": [[float(p.mediabox.width), float(p.mediabox.height), p.rotation]
                     for p in reader.pages],
        "han_characters": sum(len(re.findall(r"[\u3400-\u9fff]", p.extract_text() or ""))
                              for p in reader.pages),
    }


def check_titles(path, original, translated):
    first = PdfReader(path).pages[0].extract_text() or ""

    def canonical(text):
        # TeX writes quotes as `` and ''; the PDF has the typeset curly ones.
        return re.sub(r"[\s`'\"\u2018\u2019\u201c\u201d]+", "", unicodedata.normalize("NFKC", text))

    verified = {}
    for name, title in (("original", original), ("translated", translated)):
        if title is None:
            continue
        if re.search(r"[\\{}$%~^_&#]|--", title):
            verified[name] = "requires-visual-review"
        elif (canonical(title) not in canonical(first)
              # A long title may be hyphenated at a line break ("En-\ngines").
              and canonical(title) not in canonical(re.sub(r"-[ \t]*\n", "", first))):
            raise ValueError(f"PDF 首页面没有检测到完整的 {name} 标题")
        else:
            verified[name] = "found-on-first-page"
    return verified


def verify_bibliography(original, translated):
    def keys(path):
        return {name for name in PdfReader(path).named_destinations if name.startswith("cite.")}

    expected, actual = keys(original), keys(translated)
    if expected != actual:
        raise ValueError(f"参考文献锚点不一致（基线 {len(expected)} 项，译文 {len(actual)} 项）")
    return len(actual)


def direct_links(path):
    """Resolve pre-instrumented ref-/cite- destinations to explicit coordinates."""
    reader = PdfReader(path)
    names = reader.named_destinations
    writer = PdfWriter(clone_from=reader)
    counts = {"ref-": 0, "cite-": 0}
    targets = {"ref-": set(), "cite-": set()}
    placements = {}
    modified = False

    page_indices = {
        page.indirect_reference.idnum: index
        for index, page in enumerate(reader.pages)
        if page.indirect_reference is not None
    }
    page_indices.update({
        page.indirect_reference.idnum: index
        for index, page in enumerate(writer.pages)
        if page.indirect_reference is not None
    })
    named_by_signature = defaultdict(set)
    for name, destination in names.items():
        if not (name.startswith("ref-") or name.startswith("cite-")):
            continue
        if destination.typ != "/XYZ":
            continue
        try:
            index = reader.get_destination_page_number(destination)
            signature = (index, float(destination.left), float(destination.top))
        except (AttributeError, TypeError, ValueError):
            continue
        named_by_signature[signature].add(name)

    def array_destination(value):
        """Return (page index, x, y) for a page-array /XYZ destination."""
        value = value.get_object() if hasattr(value, "get_object") else value
        if not isinstance(value, ArrayObject) or len(value) < 4 or value[1] != "/XYZ":
            return None
        page_ref = value[0]
        index = page_indices.get(getattr(page_ref, "idnum", None))
        if index is None:
            return None
        try:
            x, y = float(value[2]), float(value[3])
        except (TypeError, ValueError):
            return None
        return index, x, y

    for page_index, page in enumerate(writer.pages):
        for annotation in page.get("/Annots", []):
            link = annotation.get_object()
            action = link.get("/A")
            action = action.get_object() if action else None
            if link.get("/Subtype") != "/Link" or not action or action.get("/S") != "/GoTo":
                continue
            name = action.get("/D")
            destination_name = None
            if isinstance(name, str):
                prefix = next((prefix for prefix in counts if name.startswith(prefix)), None)
                if prefix is None:
                    continue
                destination = names.get(name)
                if not destination or destination.typ != "/XYZ":
                    raise ValueError(f"引用目标不存在或缺少 XYZ 坐标：{name}")
                index = reader.get_destination_page_number(destination)
                if not isinstance(index, int) or not 0 <= index < len(writer.pages):
                    raise ValueError(f"引用目标页无效：{name}")
                x, y = float(destination.left), float(destination.top)
                destination_name = name
            else:
                resolved = array_destination(name)
                if resolved is None:
                    continue
                index, x, y = resolved
                candidates = named_by_signature.get((index, x, y), ())
                destination_name = next(
                    (candidate for candidate in candidates
                     if candidate.startswith("ref-") or candidate.startswith("cite-")),
                    None,
                )
                if destination_name is None:
                    continue
                prefix = next((prefix for prefix in counts
                               if destination_name.startswith(prefix)), None)
                if prefix is None:
                    continue
            bounds = writer.pages[index].mediabox
            if not (math.isfinite(x) and math.isfinite(y)
                    and bounds.left <= x <= bounds.right and bounds.bottom <= y <= bounds.top):
                raise ValueError(f"引用目标超出页面：{destination_name}")
            rect = [float(value) for value in link.get("/Rect", [])]
            if (len(rect) != 4 or not all(map(math.isfinite, rect))
                    or rect[0] >= rect[2] or rect[1] >= rect[3]):
                raise ValueError(f"引用的点击区域无效：{destination_name}")
            if prefix == "ref-":
                placements.setdefault((page_index, destination_name), []).append(rect)
            if isinstance(name, str):
                action[NameObject("/D")] = ArrayObject([
                    writer.pages[index].indirect_reference, NameObject("/XYZ"),
                    FloatObject(x), FloatObject(y), FloatObject(0),
                ])
                modified = True
            counts[prefix] += 1
            targets[prefix].add(destination_name)
    generated = {name for name in names if re.fullmatch(r"cite-\d+-.+", name)}
    if generated:
        if generated != targets["cite-"] or counts["cite-"] < len(generated):
            raise ValueError("逐次返回链接未覆盖所有正文引用")
        for name in generated:
            key = name.split("-", 2)[2]
            anchor = names[name]
            page = reader.get_destination_page_number(anchor)
            x, y = float(anchor.left), float(anchor.top)
            rectangles = placements.get((page, "ref-" + key), [])
            if not any(left - 8 <= x <= right + 8 and bottom - 8 <= y <= top + 24
                       for left, bottom, right, top in rectangles):
                raise ValueError(f"返回锚点未对准正文点击区域：{name}")
    if modified:
        temporary = path.with_suffix(".direct.pdf")
        writer.write(temporary)
        temporary.replace(path)
    return {"links": counts, "targets": {key: sorted(value) for key, value in targets.items()}}


def render_hashes(pdf, folder, executable=None):
    executable = executable or shutil.which("pdftoppm")
    if not executable:
        raise ValueError("渲染校验需要 Poppler 的 pdftoppm，可用 --pdftoppm 指定")
    folder.mkdir()
    try:
        subprocess.run([str(executable), "-r", "96", "-png", str(pdf), str(folder / "page")],
                       check=True, timeout=360, stdout=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"PDF 渲染超时（超过 360 秒）：{pdf}") from error
    return [hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.glob("page-*.png"))]


def publish(directory, work, artifacts):
    """Publish a complete bundle with a single same-filesystem directory rename."""
    staged = work / "delivery"
    staged.mkdir()
    for name, source in artifacts.items():
        shutil.copyfile(source, staged / name)
    if directory.exists():
        raise FileExistsError(f"交付目录已存在：{directory}")
    staged.rename(directory)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python postprocess_pdf.py main.pdf")
    print(direct_links(Path(sys.argv[1])))
