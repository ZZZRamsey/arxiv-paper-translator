# arXiv Paper Translator

**把 arXiv 论文译成中文 PDF，保留公式、图表和中英文标题。**

输入 arXiv 编号、摘要链接或 PDF 链接。工具会锁定论文版本，下载对应的 LaTeX 源码，用 OpenRouter 翻译正文，再重新编译和核验 PDF。

[快速开始](#快速开始) · [常用参数](#常用参数) · [输出文件](#输出文件) · [验证与限制](#验证与限制)

## 快速开始

### 1. 安装

需要 **macOS**（含 `sandbox-exec`）、**Python 3.9+**、Tectonic、BasicTeX 或 MacTeX、Poppler 和可用的中文字体。默认字体为 `Songti SC`。

如果使用 Homebrew，可安装 [Tectonic](https://formulae.brew.sh/formula/tectonic) 和 [Poppler](https://formulae.brew.sh/formula/poppler)：

~~~bash
brew install tectonic poppler
git clone https://github.com/ZZZRamsey/arxiv-paper-translator.git
cd arxiv-paper-translator
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
~~~

### 2. 翻译一篇论文

下面三种写法指向同一篇论文，任选一种运行。

~~~bash
arxiv-translate 2503.09516
arxiv-translate https://arxiv.org/abs/2503.09516
arxiv-translate https://arxiv.org/pdf/2503.09516
~~~

首次交互运行时，终端会提示输入 OpenRouter API key，输入内容不会回显。批处理可由运行环境提供 `OPENROUTER_API_KEY`。翻译请求会将待译文本发送给 OpenRouter，并使用对应账户的额度。

编译使用 **Tectonic 本地宏包缓存**，在隔离环境中离线运行。源码明确要求 PDFLaTeX 时，英文基线自动使用 BasicTeX/MacTeX，中文翻译副本使用 Unicode XeTeX 并应用兼容补丁。首次运行若提示缺少宏包，请先用可信的本地 LaTeX 文档预热所需依赖，或用 BasicTeX 的 `tlmgr --usermode install <package>` 安装到用户 TeX 树，再重试。旧版缓存无法提供的依赖可用 `--tex-overlay` 补充。

## 常用参数

| 参数 | 用途 |
| --- | --- |
| `--output DIR` | 指定输出目录，默认 `./output` |
| `--save-source` | 在 PDF 之外保存可重建的 LaTeX 源码 ZIP |
| `--model ID` | 选择 OpenRouter 模型，优先于 `OPENROUTER_MODEL`。默认 [DeepSeek V3](https://openrouter.ai/deepseek/deepseek-chat)（`deepseek/deepseek-chat`） |
| `--jobs N` | 并发数，范围 1–8，默认 4 |
| `--max-requests N` | 本次模型请求上限，含重试，默认 500。设为 0 时只复用译文缓存 |
| `--font NAME` | 指定已安装的中文字体 |
| `--root FILE` | 多个根 TeX 文件无法自动区分时，指定源码包内的相对路径 |
| `--tex-overlay DIR` | 加载可信的本地宏包目录，不覆盖原稿文件 |
| `--pdftoppm PATH` | 手动指定 Poppler 的渲染程序 |
| `--strict` | 如有待复核事项，返回非零状态，将产物保留在工作目录 |

例如，固定论文版本并额外保留源码：

~~~bash
arxiv-translate 2503.09516v5 --output ./translated --save-source
~~~

## 输出文件

| 路径（以默认目录为例） | 内容 |
| --- | --- |
| `output/<arxiv-id>_zh_CN.pdf` | 中文 PDF，首页保留中英文标题 |
| `output/<arxiv-id>_zh_CN_latex.zip` | 可选源码包，含构建说明、哈希记录和引文链接后处理脚本 |
| `output/.arxiv-work/<run>/` | 下载原件、编译日志、逐页渲染和 `verification.json` |
| `output/.translation-cache/` | 按原文、模型和提示词区分的译文缓存 |

终端会显示下载、翻译、编译和核验进度，成功后打印 PDF 的绝对路径。运行中断后，用相同输出目录重试可复用已通过校验的译文。已有交付文件不会被覆盖。即使使用 `--max-requests 0`，从 arXiv 下载原稿仍需联网。

## 验证与限制

1. **锁定原稿。** 解析 arXiv 版本，下载同版 PDF 与源码，校验归档路径并记录 SHA-256。
2. **保留 LaTeX 结构。** 保护公式、引文键和控制序列，保留原图及英文表格内容，翻译正文和图表说明。
3. **编译并独立重建。** 对支持的 `natbib + hyperref` 论文生成双向引文链接。使用独立源码副本再次编译，逐页比较两份中文 PDF 的渲染结果。

首次发布在独立安装环境通过 **17 项测试**和一次 OpenRouter 实时请求测试。[SWE-agent v3](https://arxiv.org/abs/2405.15793v3) 的 PDF 与可选 ZIP 流程均已实测。两条流程复用译文缓存，各生成 113 页，并通过独立重建比对。

工具适用于提供可编译 LaTeX 源码的 arXiv 论文。仅 PDF 的稿件、扫描件、动态生成的输入树和其他文献后端（例如 `biblatex`）目前不在验证范围内。中文译文可能重新分页，逐页重建一致也不能替代译文语义和版式的人工复核。

~~~bash
python -m unittest discover -s tests -v
~~~

LaTeX 集成测试需要 macOS 和已预热的 Tectonic 缓存。测试文件见 [`tests/`](tests/)。

## 许可

仓库公开供查阅，目前未附加开源许可证。论文及第三方 LaTeX 依赖仍适用各自的许可。
