"""Copy command-line tools and the dylibs they link into a relocatable bin/ + lib/ tree.

usage: bundle_tools.py DEST TOOL [TOOL...]
Homebrew binaries point at absolute /opt/homebrew paths; here every non-system library is
copied next to the tools and the load commands are rewritten relative to the binary.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

SYSTEM = ("/usr/lib/", "/System/")


def output(*command):
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout


def rpaths(binary):
    return re.findall(r"cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (\S+)", output("otool", "-l", str(binary)))


def dependencies(binary, origin):
    """(name as recorded, resolved file) for each non-system library of `binary`."""
    found = []
    for line in output("otool", "-L", str(binary)).splitlines()[1:]:
        name = line.strip().split(" (")[0]
        if name.startswith(SYSTEM) or Path(name).name == Path(binary).name and "/" not in name:
            continue
        if name.startswith("@rpath/"):
            choices = [Path(r.replace("@loader_path", str(origin.parent)).replace("@executable_path", str(origin.parent)))
                       / name[7:] for r in rpaths(binary)]
            choices.append(origin.parent / name[7:])
        elif name.startswith("@loader_path/") or name.startswith("@executable_path/"):
            choices = [origin.parent / name.split("/", 1)[1]]
        else:
            choices = [Path(name)]
        resolved = next((c.resolve() for c in choices if c.exists()), None)
        if resolved is None:
            raise SystemExit(f"cannot resolve {name} needed by {origin}")
        if resolved == origin.resolve():
            continue  # the library's own install name
        found.append((name, resolved))
    return found


def licenses(dest, sources):
    """Ship each Homebrew formula's license texts and say where its source comes from."""
    folder = dest / "licenses"
    folder.mkdir()
    formulas = {}
    for source in sources:
        parts = source.parts
        if "Cellar" in parts:
            index = parts.index("Cellar")
            formulas[parts[index + 1]] = Path(*parts[:index + 3])
    lines = ["Third-party software in this folder", "",
             "The command-line tools in ../bin and the libraries in ../lib are unmodified builds",
             "from Homebrew (https://brew.sh); only their library load paths were rewritten.",
             "Source for each is available through its Homebrew formula at the version listed:",
             "https://github.com/Homebrew/homebrew-core (Formula/<first letter>/<name>.rb).", ""]
    for name, prefix in sorted(formulas.items()):
        lines.append(f"- {name} {prefix.name}")
        target = folder / name
        for item in sorted(prefix.iterdir()):
            if item.is_file() and re.match(r"(?i)(copying|licen[cs]e|notice|authors)", item.name):
                target.mkdir(exist_ok=True)
                shutil.copyfile(item, target / item.name)
        if not target.is_dir():
            lines[-1] += "  (no license file in the Homebrew package; see the formula)"
    (folder / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    dest = Path(sys.argv[1])
    bin_dir, lib_dir = dest / "bin", dest / "lib"
    shutil.rmtree(dest, ignore_errors=True)
    bin_dir.mkdir(parents=True)
    lib_dir.mkdir()
    pending = []
    for tool in sys.argv[2:]:
        source = Path(shutil.which(tool) or tool).resolve()
        target = bin_dir / Path(tool).name
        shutil.copyfile(source, target)
        target.chmod(0o755)
        pending.append((target, source, "@executable_path/../lib/"))
    done = {}
    while pending:
        target, source, prefix = pending.pop()
        for name, resolved in dependencies(target, source):
            copy = lib_dir / resolved.name
            if resolved not in done:
                shutil.copyfile(resolved, copy)
                copy.chmod(0o644)
                done[resolved] = copy
                subprocess.run(["install_name_tool", "-id", "@loader_path/" + copy.name, str(copy)],
                               check=True, capture_output=True)
                pending.append((copy, resolved, "@loader_path/"))
            subprocess.run(["install_name_tool", "-change", name, prefix + resolved.name, str(target)],
                           check=True, capture_output=True)
    for path in [*lib_dir.iterdir(), *bin_dir.iterdir()]:
        subprocess.run(["codesign", "--force", "--sign", "-", str(path)], check=True, capture_output=True)
        left = [line for line in output("otool", "-L", str(path)).splitlines()[1:]
                if "/opt/homebrew" in line or "/usr/local" in line]
        if left:
            raise SystemExit(f"{path} still links outside the bundle: {left}")
    licenses(dest, [Path(shutil.which(tool) or tool).resolve() for tool in sys.argv[2:]] + list(done))
    size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file()) / 1e6
    print(f"bundled {len(sys.argv) - 2} tools and {len(done)} libraries, {size:.0f} MB")


if __name__ == "__main__":
    main()
