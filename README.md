# arXiv 论文中译

输入 arXiv 编号、摘要链接或 PDF 链接。程序锁定版本，下载同版 PDF 和 LaTeX 源码，使用 OpenRouter 翻译，并生成可复核的中文 PDF 和 LaTeX ZIP。

## 安装

当前构建后端要求 macOS、`sandbox-exec`、Python 3.9+、Tectonic、Poppler 的 `pdftoppm` 和已安装的中文字体。推荐使用链接到受支持 OpenSSL 的 Python。默认字体为 `Songti SC`，可用 `--font` 修改。构建阶段关闭网络并使用 Tectonic 本地缓存。若缺包，应先用可信的本地 LaTeX 文档初始化宏包缓存，再重跑 arXiv 任务。缺少隔离后端时程序会停止。可用 `--pdftoppm` 指定 Poppler 可执行文件。

~~~sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
~~~

## 使用

~~~sh
arxiv-translate 2503.09516
arxiv-translate 'https://arxiv.org/abs/2503.09516' --output ./translated
arxiv-translate 'https://arxiv.org/pdf/2503.09516v5' --model deepseek/deepseek-chat-v3-0324
~~~

程序从环境变量 `OPENROUTER_API_KEY` 读取密钥。交互式终端未设置变量时会隐藏输入并提示。默认模型是 OpenRouter 的 [DeepSeek V3](https://openrouter.ai/deepseek/deepseek-chat)，ID 为 `deepseek/deepseek-chat`。可用 `--model` 或 `OPENROUTER_MODEL` 切换，命令行优先。`--jobs` 控制并发，默认 4。`--max-requests` 默认 500，涵盖批量请求和重试。设为 0 可离线复用已有译文缓存，下载 arXiv 仍需网络。OpenRouter 使用该账户额度，并将待译正文发送给模型供应商。

默认只在输出根目录保存 `<arxiv-id>_zh_CN.pdf`，封面标题同时保留中文译名和原标题。用 `--save-source` 额外保存源码 ZIP。中间状态实时打印，结束时打印 PDF 的绝对路径。编译日志、工作源码及 `verification.json` 位于输出目录的 `.arxiv-work/`。自动验收通过后，待人工复核的事项仍会明确列出。若要在待复核时禁止发布 PDF，使用 `--strict`。

## 输出与依赖

默认输出到当前目录下的 `output/`，用 `--output` 可以指定其他路径。密钥只从环境变量或终端隐藏输入取得。

若 Tectonic 的旧缓存版本缺少某个可信宏包，可用 `--tex-overlay /path/to/verified-packages` 给该论文补充依赖。补充文件会纳入哈希记录，且无法覆盖原稿。

## 实现

1. 显式版本直接锁定，无版本输入从 arXiv 提交记录查最新版。固定版本的 PDF 与源码分别下载并计算 SHA-256。源码解包拒绝路径穿越、重复文件、符号链接及特殊文件。
2. 识别根 TeX，并在 macOS 文件访问限制及离线模式下编译英文基线。多个候选根无法唯一确定时，可用 `--root` 指定相对路径。
3. 沿静态 TeX 输入树翻译，用占位符保护公式、控制序列和引文键。每个批次最多六块，失败的译块单独重试。新缓存按完整 TeX 原文、模型和提示词区分。缓存位于 `.translation-cache/`。旧版键无法区分公式上下文，新版不会读取旧键。
4. 用 xeCJK 编译中文 PDF。对 natbib + hyperref 增加逐次引用和返回链接，迭代更新返回页码，将目标转成显式 XYZ 坐标。源码 ZIP 包含构建说明、链接后处理脚本、译块记录和哈希。
5. 在独立源码副本中重建并逐页比较渲染。指定 `--save-source` 时，独立重建使用解压后的 ZIP。报告原文和译文版式差异、请求数、缓存命中、分阶段时间及 API 返回的用量。

## 适用范围

支持可下载且能用 Tectonic 编译的 LaTeX 源码。PDF-only、OCR、动态生成的输入树、biblatex 和其他引用后端需要额外适配。复杂自定义宏、非标准表格、译文语义完整性和原稿版式对齐需要复核。逐页像素比较的是中文产物和独立重建版，原稿与译文的逐页版式等价仍待人工确认。

## 测试与许可

安装后在仓库根目录运行 `python -m unittest discover -s tests -v`。LaTeX 集成测试依赖 macOS 和已预热的 Tectonic 缓存。缓存目录中的成功译块可在编译或网络中断后重用。

公开仓库供查阅。本版本未附加开源许可证，论文和第三方 LaTeX 依赖仍适用各自的许可。
