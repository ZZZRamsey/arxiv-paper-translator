# arXiv Paper Translator 完整教程

这份教程说明如何安装项目、选择翻译后端、保持原始 LaTeX 排版、检查输出文件，以及排查常见问题。

## 1. 项目要求

项目当前面向 macOS，运行时需要以下组件：

- Python 3.9 或更高版本
- `sandbox-exec`
- Tectonic、BasicTeX 或 MacTeX
- Poppler 的 `pdftoppm`
- 一个可用的中文字体，默认使用 `Songti SC`
- 网络访问 arXiv。使用 OpenRouter 时还需要访问 OpenRouter

源码明确使用 PDFLaTeX 的论文，需要本机存在 `pdflatex`。使用 `--texlive` 时，项目用 PDFLaTeX 编译英文基线，用 XeLaTeX 编译中文译稿。

## 2. 安装项目

```bash
brew install poppler
git clone https://github.com/ZZZRamsey/arxiv-paper-translator.git
cd arxiv-paper-translator
python3 -m venv .venv
.venv/bin/python -m pip install .
```

如果本机没有 BasicTeX 或 MacTeX，请先安装其中一个。只使用 Tectonic 的论文可以直接使用 Tectonic 的本地宏包缓存。

```bash
brew install --cask mactex-no-gui
```

安装后重新打开终端，确认编译器可用：

```bash
which pdflatex
which xelatex
which bibtex
which pdftoppm
```

## 3. 使用 OpenRouter

这是项目原有的远程翻译方式。先设置 API Key：

```bash
export OPENROUTER_API_KEY="你的 OpenRouter API Key"
```

翻译一篇论文：

```bash
cd /Users/ramseyzhu/zls/code/arxiv-paper-translator
.venv/bin/python -m paper_translate 2503.09516 --output ./output
```

也可以使用摘要页或 PDF 链接：

```bash
.venv/bin/python -m paper_translate https://arxiv.org/abs/2503.09516
.venv/bin/python -m paper_translate https://arxiv.org/pdf/2503.09516.pdf
```

## 4. 使用本地 Ollama 模型

启动 Ollama 并下载模型：

```bash
ollama serve
ollama pull qwen3.5:9b
```

在另一个终端运行项目：

```bash
cd /Users/ramseyzhu/zls/code/arxiv-paper-translator
.venv/bin/python -m paper_translate 2511.20785v3 \
  --local \
  --model qwen3.5:9b \
  --output /Users/ramseyzhu/zls/paper_translate
```

项目默认连接 `http://127.0.0.1:11434`。如果 Ollama 使用其他地址，可以设置：

```bash
OLLAMA_HOST=http://127.0.0.1:11434 \
.venv/bin/python -m paper_translate 2511.20785v3 --local --model qwen3.5:9b
```

本地模式默认会进行译文复核。需要缩短运行时间时可以加上 `--no-review`：

```bash
.venv/bin/python -m paper_translate 2511.20785v3 \
  --local --model qwen3.5:9b --no-review
```

## 5. 使用当前 ChatGPT 会话

当前 ChatGPT 后端通过目录文件与项目交换请求，不需要 OpenRouter API Key。

先在终端启动项目：

```bash
cd /Users/ramseyzhu/zls/code/arxiv-paper-translator
.venv/bin/python -m paper_translate 2511.20785v3 \
  --chatgpt ./translation-queue \
  --output /Users/ramseyzhu/zls/paper_translate
```

项目会在 `translation-queue` 中生成：

```text
<随机ID>.request.json
```

当前 ChatGPT 会话读取这个文件，按照其中的 system 和 user 消息完成翻译，然后将 JSON 字符串写入：

```text
<随机ID>.response.json
```

项目检测到响应后继续处理。请求完成后，这两个临时文件会被删除。

如果只在普通终端运行而没有 ChatGPT 会话处理队列，程序会等待响应文件。

## 6. 保持原始 LaTeX 排版

保持原始模板、标题样式、作者区域、行号和引用样式时，使用：

```bash
cd /Users/ramseyzhu/zls/code/arxiv-paper-translator
.venv/bin/python -m paper_translate 2511.20785v3 \
  --local \
  --model qwen3.5:9b \
  --original-layout \
  --texlive \
  --output /Users/ramseyzhu/zls/paper_translate
```

使用当前 ChatGPT 会话时，将 `--local --model qwen3.5:9b` 换成：

```bash
--chatgpt ./translation-queue
```

完整命令如下：

```bash
cd /Users/ramseyzhu/zls/code/arxiv-paper-translator
.venv/bin/python -m paper_translate 2511.20785v3 \
  --chatgpt ./translation-queue \
  --original-layout \
  --texlive \
  --output /Users/ramseyzhu/zls/paper_translate
```

`--original-layout` 会跳过项目额外注入的双语标题、引用颜色和参考文献回跳文字。中文正文长度发生变化后，分页数量和浮动体位置仍可能变化，这是 LaTeX 重新排版的结果。

`--texlive` 会执行以下编译流程：

1. 用 PDFLaTeX 编译英文基线。
2. 用 XeLaTeX 编译中文译稿。
3. 如果源码使用 BibTeX，运行 BibTeX 并重新编译。
4. 对中文 PDF 做引用、页面、中文文字和独立重建检查。

## 7. 输出文件

默认会生成类似以下文件：

```text
output/2511.20785_zh_CN_LongVT.pdf
output/.arxiv-work/<运行目录>/verification.json
output/.translation-cache/<缓存文件>.txt
```

简称由 AI 根据论文标题和摘要提取。没有识别到明确简称时，文件名会回退到不带简称的形式。

如果需要同时保存可重建的源码包：

```bash
.venv/bin/python -m paper_translate 2511.20785v3 \
  --local --model qwen3.5:9b \
  --original-layout --texlive \
  --save-source \
  --output ./output
```

## 8. 保存到 Zotero

项目可以通过 Zotero 本机 Local API，把生成的 PDF 添加到对应的论文条目下：

```bash
.venv/bin/python -m paper_translate 2511.20785v3 \
  --local --model qwen3.5:9b \
  --original-layout --texlive \
  --zotero \
  --output ./output
```

使用前需要在 Zotero 设置中启用本机应用访问，并允许项目写入。项目按 arXiv 编号匹配条目，找不到唯一条目时会停止上传，避免附件挂到错误的论文上。

## 9. 常用参数

| 参数 | 作用 |
| --- | --- |
| `--chatgpt DIR` | 通过目录文件使用当前 ChatGPT 会话 |
| `--local` | 使用本机 Ollama |
| `--model NAME` | 指定 OpenRouter 或 Ollama 模型 |
| `--original-layout` | 沿用原始模板的版式和标题样式 |
| `--texlive` | 使用 PDFLaTeX、XeLaTeX 和 BibTeX |
| `--no-review` | 本地模型跳过译文复核 |
| `--jobs N` | 设置并发翻译数量，默认 4 |
| `--max-requests N` | 设置模型请求上限，默认云端 500、本地和 ChatGPT 会话 5000 |
| `--font NAME` | 指定中文字体，默认 `Songti SC` |
| `--root FILE` | 指定源码包中的根 TeX 文件 |
| `--tex-overlay DIR` | 添加本地 TeX 宏包目录 |
| `--save-source` | 保存可重建的源码 ZIP |
| `--strict` | 有待复核事项时不发布最终 PDF |

查看完整帮助：

```bash
.venv/bin/python -m paper_translate --help
```

## 10. 本地配置

项目会读取：

```text
~/.config/arxiv-paper-translator/local.json
```

配置文件权限需要设置为用户可读写：

```bash
mkdir -p ~/.config/arxiv-paper-translator
chmod 700 ~/.config/arxiv-paper-translator
chmod 600 ~/.config/arxiv-paper-translator/local.json
```

本地模型默认配置示例：

```json
{
  "local": true,
  "local_model": "qwen3.5:9b",
  "output": "/Users/ramseyzhu/zls/paper_translate"
}
```

使用 `--public-defaults` 可以忽略这份本机配置。

## 11. 测试项目

运行单元测试：

```bash
cd /Users/ramseyzhu/zls/code/arxiv-paper-translator
.venv/bin/python -m unittest discover -s tests -v
```

LaTeX 集成测试需要 macOS 和已经准备好的本地 TeX 宏包缓存。

## 12. 常见问题

### 找不到中文字体

查看系统字体名称：

```bash
fc-list | head
```

然后指定字体：

```bash
.venv/bin/python -m paper_translate 2511.20785v3 \
  --local --model qwen3.5:9b \
  --font "Songti SC"
```

### 编译时提示缺少 LaTeX 宏包

先确认 `pdflatex` 和 `xelatex` 来自同一套 TeX 安装。需要额外宏包时，可以使用 TeX Live 的包管理器安装，或者使用项目参数加载可信的本地宏包目录：

```bash
.venv/bin/python -m paper_translate 2511.20785v3 \
  --local --model qwen3.5:9b \
  --original-layout --texlive \
  --tex-overlay /path/to/tex-overlay
```

### 程序等待 ChatGPT 响应

检查队列目录中是否存在 `.request.json` 文件。当前 ChatGPT 会话需要读取请求内容，并写入同名的 `.response.json` 文件。响应内容必须是非空 JSON 字符串。

### 需要重新翻译

删除对应输出目录中的 `.translation-cache`，或使用新的输出目录重新运行：

```bash
.venv/bin/python -m paper_translate 2511.20785v3 \
  --local --model qwen3.5:9b \
  --output ./output-new
```

### 只想复用已有缓存

将请求上限设为 0：

```bash
.venv/bin/python -m paper_translate 2511.20785v3 \
  --local --max-requests 0
```

这时项目仍然需要联网下载指定版本的 arXiv 源码和 PDF。

