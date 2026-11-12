"""Optional per-machine defaults, outside the source tree."""

import json
from pathlib import Path


def local_settings():
    path = Path.home() / ".config" / "arxiv-paper-translator" / "local.json"
    if not path.exists():
        return {}
    if path.stat().st_mode & 0o077:
        raise ValueError(f"本地配置权限过宽，请运行 chmod 600 {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("本地配置需要 JSON 对象")
    if not isinstance(data.get("local", False), bool):
        raise ValueError("本地配置字段 local 必须是 true 或 false")
    for name in ("output", "api_key", "openai_api_key", "openai_base_url",
                 "openai_model", "pdftoppm", "tex_overlay", "local_model"):
        if name in data and not isinstance(data[name], str):
            raise ValueError(f"本地配置字段 {name} 必须是字符串")
    if "openai" in data and not isinstance(data["openai"], bool):
        raise ValueError("本地配置字段 openai 必须是 true 或 false")
    overlays = data.get("tex_overlays", {})
    if not isinstance(overlays, dict) or any(not isinstance(value, str) for value in overlays.values()):
        raise ValueError("tex_overlays 必须是 arXiv 编号到路径的对象")
    return data
