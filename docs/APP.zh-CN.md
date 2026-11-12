# arXiv Translator：macOS app 使用与打包

## 安装和首次打开

1. 打开 `arXiv-Translator-<版本>-arm64.dmg`，把 **arXiv Translator** 拖进“应用程序”。
2. 这个 app 目前没有 Apple 开发者签名。首次打开时系统会拦截，按下面任一方式放行一次即可：
   - 打开“系统设置 → 隐私与安全性”，在页面下方找到 arXiv Translator，点“仍要打开”；
   - 或在终端运行：

     ~~~bash
     xattr -dr com.apple.quarantine "/Applications/arXiv Translator.app"
     ~~~
3. 首次启动会显示“开始前的准备”，逐项列出环境是否就绪，并可以在里面保存 API key 和默认设置。

app 内置了 Python 运行环境、Tectonic 和 Poppler（pdftoppm），不需要另外安装 Python 或 Homebrew。

## 还需要准备什么

| 项目 | 是否必须 | 说明 |
| --- | --- | --- |
| TeX 基础宏包 | 自动 | 首次编译时联网下载到 `~/Library/Caches/TectonicProject.Tectonic`（约 60 MB）。首次通常需要 5–15 分钟，取决于网络。之后缺少的宏包在“自动下载缺失的 TeX 宏包”打开时按需下载。论文源码本身始终在断网的沙箱里编译。 |
| 翻译引擎 | 任选其一 | **OpenRouter**：在准备面板里填 API key。**OpenAI API / 兼容接口**：在准备面板里填 OpenAI 的 API key；连接自建的 vLLM 等兼容服务时，再填接口地址（如 `http://127.0.0.1:8000/v1`）和服务端模型名，服务不要求 key 时可留空。**Ollama**：安装 Ollama 并 `ollama pull qwen3.5:9b`，待译文本不出本机。 |
| TeX Live | 可选 | 多数模板（NeurIPS、ICLR、ICML、CVPR 等）用内置的 Tectonic 就能编译。少数模板只支持 PDFLaTeX（例如 ACL 系列），遇到时程序会自动改用本机 TeX Live；没装时会给出提示。安装：`brew install --cask mactex-no-gui`。 |
| Zotero | 可选 | 打开“保存到 Zotero”后把译文挂到对应条目。 |

设置保存在 `~/.config/arxiv-paper-translator/local.json`（仅本人可读），界面状态保存在
`~/Library/Application Support/arXiv Translator/`。默认译文保存在“文稿/arXiv 译文”。

## 发布前测试覆盖

1.0 发布前，用 9 篇不同模板的 arXiv 论文跑过完整流水线（下载、英文基线、翻译、中文编译、独立重建、逐页比对），翻译环节用固定输出的替身模型代替真实模型：

| 论文 | 模板 | 仅内置 Tectonic | 有 TeX Live 时 |
| --- | --- | --- | --- |
| 2503.09516 Search-R1 | COLM | 通过 | 通过 |
| 1706.03762 Transformer | NeurIPS | 通过 | 通过 |
| 2106.09685 LoRA | ICLR | 通过 | 通过 |
| 2010.11929 ViT | ICLR（含 TikZ） | 通过 | 通过 |
| 2601.13719 HAVEN | CVPR | 通过 | 通过 |
| 2511.20785 LongVT | CVPR | 通过 | 通过 |
| 2405.15793 SWE-agent | NeurIPS（用到 twemoji） | 需要用“本地宏包目录”补充 twemoji | 同左 |
| 1810.04805 BERT | ACL | 不支持，需要 TeX Live | 通过（无引用回跳导航） |
| 2312.00752 Mamba | biblatex | 不支持 | 不支持 |

使用 biblatex 的论文目前无法处理。真实模型的译文质量另见 README 的“验证与限制”。

## 限制

- 只支持 macOS。当前安装包为 Apple 芯片（arm64）构建，且要求的最低系统版本与构建机器相同，因为内置的 Tectonic 和 Poppler 取自构建机器上的 Homebrew。
- 关闭窗口即退出 app，正在进行的翻译会被取消（会先询问）；已完成的段落留在缓存里，下次可接着翻。

## 自己构建

需要 Xcode Command Line Tools、Homebrew 的 `tectonic` 和 `poppler`，以及 Python 3.9+：

~~~bash
brew install tectonic poppler
./packaging/build_app.sh
~~~

产物在 `dist/`：`arXiv Translator.app` 和 `.dmg`。脚本做了这些事：

1. 用 PyInstaller 把 `paper_translate` 打成独立后端（`Contents/Resources/backend`）；
2. 编译 `packaging/Launcher.swift`：一个原生窗口，启动后端并显示它的页面；
3. 用 `packaging/bundle_tools.py` 把 Tectonic、pdftoppm 及其动态库复制到 `Contents/Resources/tools` 并改成相对路径；
4. 生成图标、`Info.plist`，做 ad-hoc 签名，打出 `.dmg`。

### 正式签名和公证

有 Apple Developer 账号时，把脚本里的 ad-hoc 签名换成开发者证书并公证，别人打开就不会被拦截：

~~~bash
codesign --force --deep --options runtime --sign "Developer ID Application: <你的名字> (<TEAMID>)" "dist/arXiv Translator.app"
xcrun notarytool submit dist/arXiv-Translator-*.dmg --keychain-profile <profile> --wait
xcrun stapler staple dist/arXiv-Translator-*.dmg
~~~

### 内置第三方软件的许可

安装包里带有 Tectonic（MIT）、Poppler（GPL-2.0-or-later）以及它们依赖的库（ICU、HarfBuzz、FreeType、NSS 等，各自的开源许可）。
这些软件都是 Homebrew 的原样构建，只改写了动态库的加载路径。各自的许可文本和版本清单随包放在 app 的 `Contents/Resources/tools/licenses/` 里，其中说明了如何通过 Homebrew 配方获取对应源码。
