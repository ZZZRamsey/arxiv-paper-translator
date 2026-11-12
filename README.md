# arXiv Paper Translator

**把 arXiv 论文译成中文 PDF，保留公式、图表和中英文标题。**

输入 arXiv 编号、摘要链接或 PDF 链接。工具会锁定论文版本，下载对应的 LaTeX 源码，通过选定的 AI 后端翻译正文，再重新编译和核验 PDF。

[快速开始](#快速开始) · [常用参数](#常用参数) · [输出文件](#输出文件) · [验证与限制](#验证与限制) · [完整教程](docs/TUTORIAL.zh-CN.md)

## 快速开始

完整的安装、OpenRouter、Ollama、当前 ChatGPT 会话、原始 LaTeX 排版、输出文件和故障排查说明见 [完整教程](docs/TUTORIAL.zh-CN.md)。下面保留最短可执行命令。

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

### 最短命令

使用本地 Ollama，并沿用原始 LaTeX 排版：

~~~bash
.venv/bin/python -m paper_translate 2511.20785v3 --local --model qwen3.5:9b --original-layout --texlive --output ./output
~~~

使用当前 ChatGPT 会话，并沿用原始 LaTeX 排版：

~~~bash
.venv/bin/python -m paper_translate 2511.20785v3 --chatgpt ./translation-queue --original-layout --texlive --output ./output
~~~

使用 OpenRouter：

~~~bash
OPENROUTER_API_KEY="你的 API Key" .venv/bin/python -m paper_translate 2511.20785v3 --output ./output
~~~

使用 OpenAI API 或 OpenAI 兼容的远程 vLLM：

~~~bash
OPENAI_API_KEY="你的 API Key" .venv/bin/python -m paper_translate 2511.20785v3 --openai --model gpt-4o-mini --output ./output
~~~

默认接口是 `https://api.openai.com/v1/chat/completions`。远程 vLLM 可设置 `OPENAI_BASE_URL`，例如 `http://127.0.0.1:8000/v1`，并用 `OPENAI_MODEL` 指定服务端模型名。API key 也可以写入 `~/.config/arxiv-paper-translator/local.json` 的 `openai_api_key`，接口地址和模型分别使用 `openai_base_url`、`openai_model`。vLLM 不要求 key 时可以留空。

### 图形界面

不想记参数时，可以在浏览器里操作。下面的命令会在本机 `127.0.0.1:8765` 启动界面并自动打开浏览器：

~~~bash
.venv/bin/python -m paper_translate.web
~~~

重新 `pip install .` 后也可以直接运行 `arxiv-translate-ui`。界面里可以粘贴 arXiv 编号或链接，切换 OpenRouter、OpenAI API、Ollama、ChatGPT 四种翻译引擎，选择保存位置和各项开关，并查看实时进度与日志。界面只是命令行的一层表单，页面下方会显示等价的 `arxiv-translate` 命令。服务只监听本机，同一时间运行一个翻译任务；`--port` 可换端口，`--no-browser` 不自动打开浏览器。

### 2. 翻译一篇论文

下面三种写法指向同一篇论文，任选一种运行。

~~~bash
arxiv-translate 2503.09516
arxiv-translate https://arxiv.org/abs/2503.09516
arxiv-translate https://arxiv.org/pdf/2503.09516
~~~

翻译完成后，可用 `--zotero` 自动在本机 Zotero 中按 arXiv 编号查找论文条目，并把译文 PDF 保存为该条目的子附件：

~~~bash
arxiv-translate 2511.20785 --openai --zotero
~~~

该功能使用 Zotero 本机 Local API，不使用 Zotero Web API。首次使用前，在 Zotero 的“设置 → 高级”中启用“允许其他应用在本机与 Zotero 通信”，并在 Zotero 10 的授权对话框中允许 `arXiv Paper Translator` 写入。Zotero 9 只支持本机 API 读取，无法自动保存附件，需要升级到支持本机写入的版本。程序按 arXiv 编号匹配条目，匹配到零个或多个条目时会停止，避免把译文挂到错误的论文下。Zotero 中的普通文件同步仍按其现有设置执行。

首次交互运行时，终端会提示输入 OpenRouter API key，输入内容不会回显。批处理可由运行环境提供 `OPENROUTER_API_KEY` 或 `OPENAI_API_KEY`。翻译请求会按所选后端发送到 OpenRouter、OpenAI 或 OpenAI 兼容的 vLLM 服务。

### 3. 改用本地模型（可选）

加上 `--local` 后，翻译由本机的 [Ollama](https://ollama.com) 完成，不需要 API key，待译文本不会离开本机。默认模型是 `qwen3.5:9b`（约 7 GB，支持图片输入，适合 16 GB 内存的 Apple Silicon Mac）。

~~~bash
brew install --cask ollama-app
ollama pull qwen3.5:9b
arxiv-translate 2503.09516 --local
~~~

内存更小或想更快时，可用 `--model qwen3.5:4b` 换成较小的模型。`OLLAMA_HOST` 指定其他 Ollama 地址，`OLLAMA_MODEL` 指定默认本地模型。在 `~/.config/arxiv-paper-translator/local.json` 中写入 `"local": true` 可让本地模式成为默认，`"local_model"` 可固定模型。中断后重跑会复用译文缓存。

本地模式逐段翻译：先从标题和摘要生成全文统一的术语表，每段译完再由模型复核一遍，并校验数字和 LaTeX 占位符；个别段落反复出错时改为逐句翻译。`--no-review` 跳过复核，耗时约减半。

本地模式默认 4 路并发。翻译开始时会检查本机 Ollama 是否已开启相应的并行路数，并关闭其推理进程的提示缓存（该缓存在 16 GB 内存的机器上会把内存占满，使速度下降数倍）；设置不符时会自动写入 `launchctl` 环境变量并重启 Ollama，正在进行的其他 Ollama 对话会因此中断。`OLLAMA_HOST` 指向其他机器时不做任何改动。

编译使用 **Tectonic 本地宏包缓存**，在隔离环境中离线运行。源码明确要求 PDFLaTeX 时，英文基线自动使用 BasicTeX/MacTeX，中文翻译副本使用 Unicode XeTeX 并应用兼容补丁。首次运行若提示缺少宏包，请先用可信的本地 LaTeX 文档预热所需依赖，或用 BasicTeX 的 `tlmgr --usermode install <package>` 安装到用户 TeX 树，再重试。旧版缓存无法提供的依赖可用 `--tex-overlay` 补充。

### 使用当前 ChatGPT 会话并保留原文排版

在能读写本机文件的 ChatGPT / Codex 会话中，让助手运行以下命令并处理队列：

~~~bash
arxiv-translate 2511.20785v3 --chatgpt ./translation-queue --original-layout --texlive
~~~

项目将简称提取和正文翻译请求写入队列中的 `<id>.request.json`，内容为 system 和 user 消息。当前会话读取请求后，把回答编码成一个 JSON 字符串，先写临时文件，再重命名为 `<id>.response.json`。程序验证占位符并继续编译。单独在终端运行时，程序会等待会话回写。该模式无需 API 密钥。

`--original-layout` 保留模板自身的标题、行号和引用样式，译文仍由原始 LaTeX 模板排版。中文换行和浮动体分页可能与英文不同。`--texlive` 通过本机 TeX Live 的 PDFLaTeX 编译英文基线，通过 XeLaTeX 编译中文，并在需要时运行 BibTeX。

## 常用参数

| 参数 | 用途 |
| --- | --- |
| `--output DIR` | 指定输出目录，默认 `./output` |
| `--save-source` | 在 PDF 之外保存可重建的 LaTeX 源码 ZIP |
| `--local` | 用本机 Ollama 模型翻译，不调用 OpenRouter |
| `--openai` | 调用 OpenAI API 或 OpenAI 兼容的 vLLM 接口 |
| `--api-key KEY` | 本次请求使用的 API key，优先于环境变量和本机配置 |
| `--model ID` | 选择当前后端的模型。OpenRouter 优先使用 `OPENROUTER_MODEL`，OpenAI 优先使用 `OPENAI_MODEL`，本地模式下为 Ollama 模型名 |
| `--jobs N` | 并发数，范围 1–8，默认 4 |
| `--no-review` | 本地模式下跳过逐段复核 |
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
| `output/<arxiv-id>_zh_CN_<简称>.pdf` | 中文 PDF，首页保留中英文标题 |
| `output/<arxiv-id>_zh_CN_latex_<简称>.zip` | 可选源码包，含构建说明、哈希记录和引文链接后处理脚本 |
| `output/.arxiv-work/<run>/` | 下载原件、编译日志、逐页渲染和 `verification.json` |
| `output/.translation-cache/` | 按原文、模型和提示词区分的译文缓存 |

程序使用当前选定的 AI 模型从 arXiv 标题和摘要中提取作者提出的方法或模型名，保留原文大小写，例如 `2511.20785_zh_CN_LongVT.pdf`。没有明确命名时沿用原文件名。首次提取计入请求预算，后续复用简称缓存；仅有旧版译文缓存时，需先允许一次简称请求。

终端会显示下载、翻译、编译和核验进度，成功后打印 PDF 的绝对路径。运行中断后，用相同输出目录重试可复用已通过校验的译文。已有交付文件不会被覆盖。即使使用 `--max-requests 0`，从 arXiv 下载原稿仍需联网。

## 验证与限制

1. **锁定原稿。** 解析 arXiv 版本，下载同版 PDF 与源码，校验归档路径并记录 SHA-256。
2. **保留 LaTeX 结构。** 保护公式、引文键和控制序列，保留原图及英文表格内容，翻译正文和图表说明。
3. **编译并独立重建。** 对支持的 `natbib + hyperref` 论文生成双向引文链接。使用独立源码副本再次编译，逐页比较两份中文 PDF 的渲染结果。

当前测试套件包含 **29 项测试**。LaTeX 流程和 ChatGPT、Ollama 后端均有对应的测试覆盖。[SWE-agent v3](https://arxiv.org/abs/2405.15793v3) 的 PDF 与可选 ZIP 流程均已实测。翻译流程会复用译文缓存，并通过独立重建比对。

工具适用于提供可编译 LaTeX 源码的 arXiv 论文。仅 PDF 的稿件、扫描件、动态生成的输入树和其他文献后端（例如 `biblatex`）目前不在验证范围内。中文译文可能重新分页，逐页重建一致也不能替代译文语义和版式的人工复核。

~~~bash
python -m unittest discover -s tests -v
~~~

LaTeX 集成测试需要 macOS 和已预热的 Tectonic 缓存。测试文件见 [`tests/`](tests/)。

## 许可

仓库公开供查阅，目前未附加开源许可证。论文及第三方 LaTeX 依赖仍适用各自的许可。
