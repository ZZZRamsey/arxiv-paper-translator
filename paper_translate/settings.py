"""Optional per-machine defaults, outside the source tree."""

import json
from pathlib import Path


CONFIG = Path.home() / ".config" / "arxiv-paper-translator" / "local.json"


def local_settings():
    path = CONFIG
    if not path.exists():
        return {}
    if path.stat().st_mode & 0o077:
        raise ValueError(f"本地配置权限过宽，请运行 chmod 600 {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("本地配置需要 JSON 对象")
    if not isinstance(data.get("local", False), bool):
        raise ValueError("本地配置字段 local 必须是 true 或 false")
    for name in ("output", "api_key", "pdftoppm", "tex_overlay", "local_model"):
        if name in data and not isinstance(data[name], str):
            raise ValueError(f"本地配置字段 {name} 必须是字符串")
    overlays = data.get("tex_overlays", {})
    if not isinstance(overlays, dict) or any(not isinstance(value, str) for value in overlays.values()):
        raise ValueError("tex_overlays 必须是 arXiv 编号到路径的对象")
    return data


def update_settings(changes):
    """Merge values into the per-machine file; None removes a key. The file may hold an API key."""
    data = local_settings()
    for name, value in changes.items():
        if value is None:
            data.pop(name, None)
        else:
            data[name] = value
    CONFIG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = CONFIG.with_suffix(".tmp")
    pending.touch(mode=0o600, exist_ok=True)
    pending.chmod(0o600)
    pending.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pending.replace(CONFIG)
