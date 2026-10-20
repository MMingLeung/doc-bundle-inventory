# doc-bundle-inventory

**English:** A small Python library and CLI that inventories nested archives and mixed documents. It walks ZIP files (RAR and 7z are optional), repairs common Chinese filename mojibake, and writes a `manifest.json` with a file tree, SHA-256 hashes, detected types, lightweight Word/PDF metadata, duplicate hints, and filename version hints. Use it as a pre-step before MarkItDown, Docling, or a RAG index — know what is in the bundle before you convert or chunk it.

把嵌套压缩包里的 Word、PDF、Excel、图片和其它文件整理成一份结构化清单。适合作为 MarkItDown、Docling 或 RAG 入库之前的第一步：先看清包里有什么、哪些是重复的、文件名有没有乱码，再决定要不要解析正文。

## 这是什么

输入一个可能「包中包」的压缩包（外层 zip 里还有 zip，夹杂 docx、pdf、xlsx、图片等）。输出 `manifest.json`，包含：

- 文件树，以及每个文件在压缩包链上的逻辑路径
- 解压后内容的 SHA-256
- 基于文件头的类型判断（docx / xlsx / pptx 不会被当成普通 zip 再拆开）
- Word、PDF 能廉价读到的元数据：标题、作者、修改时间、页数
- 相同哈希的重复文件提示
- 从文件名推断的版本线索（`v1.2`、`终稿`、`第2版`、`final` 等）
- 对常见中文 ZIP 文件名乱码（GBK 字节被当成 CP437）的修复

遍历在内存中完成，不会把成员解压到磁盘。路径穿越（绝对路径、`..`）、过深嵌套、单文件过大、总解压体积过大、异常压缩比会被拒绝或跳过，并写入 `warnings`。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

只要标准库就能处理 ZIP。RAR / 7z 是可选依赖：

```bash
pip install -e ".[rar]"      # 还需要系统里有 unrar
pip install -e ".[py7zr]"    # 纯 Python 的 7z
pip install -e ".[all]"
```

开发与测试：

```bash
pip install -e ".[dev]"
pytest
```

## 快速开始

仓库里已经放了一份嵌套示例 `examples/sample_bundle/bundle.zip`（外层 zip → `报告/inner.zip` → txt / docx / pdf，并带一个 GBK 文件名）。

```bash
doc-bundle-inventory examples/sample_bundle/bundle.zip -o manifest.json
python -m doc_bundle_inventory examples/sample_bundle/bundle.zip -o manifest.json
```

不写 `-o` 时，JSON 打到标准输出。重新生成示例包：

```bash
python examples/build_sample_bundle.py
```

在代码里：

```python
from doc_bundle_inventory import inventory

manifest = inventory("examples/sample_bundle/bundle.zip")
for item in manifest["files"]:
    print(item["logical_path"], item["file_type"], item["sha256"][:12])
```

示例包结构：

```text
bundle.zip
├── 说明.txt                         # GBK 文件名，无 UTF-8 标志
├── 预览.png
└── 报告/
    ├── 项目说明_v1.0.txt
    ├── 项目说明_v1.2_终稿.txt
    ├── 说明_副本.txt                 # 与 说明.txt 内容相同
    ├── 副本/项目说明_v1.0.txt        # 与 v1.0 内容相同
    └── inner.zip
        └── 附件/
            ├── 备注.txt
            ├── 合同_终稿.docx        # 作者、页数
            └── 封面.pdf
```

## 示例输出

对已提交的 `examples/sample_bundle/bundle.zip` 跑一遍，摘录如下（`tree` 未展开；细节以 `files` 为准）：

```json
{
  "schema_version": 1,
  "stats": {
    "files": 9,
    "nested_archives": 1,
    "directories": 3,
    "duplicate_groups": 2,
    "warnings": 0
  },
  "duplicates": [
    {
      "sha256": "ca5bab772d590c04ee36e7b204ed3e3ace6726057b49f6c3cdac4676e58bd7a9",
      "size": 37,
      "count": 2,
      "paths": [
        "bundle.zip!/说明.txt",
        "bundle.zip!/报告/说明_副本.txt"
      ]
    }
  ],
  "files": [
    {
      "logical_path": "bundle.zip!/说明.txt",
      "member_path": "说明.txt",
      "archive_chain": ["bundle.zip"],
      "kind": "file",
      "file_type": "txt",
      "mime": "text/plain",
      "size": 37,
      "sha256": "ca5bab772d590c04ee36e7b204ed3e3ace6726057b49f6c3cdac4676e58bd7a9",
      "name_encoding": "gb18030",
      "version_hints": [],
      "metadata": null,
      "duplicate_group": "ca5bab772d590c04ee36e7b204ed3e3ace6726057b49f6c3cdac4676e58bd7a9"
    },
    {
      "logical_path": "bundle.zip!/报告/项目说明_v1.2_终稿.txt",
      "file_type": "txt",
      "name_encoding": "utf-8",
      "version_hints": ["v1.2", "终稿"]
    },
    {
      "logical_path": "bundle.zip!/报告/inner.zip!/附件/合同_终稿.docx",
      "member_path": "附件/合同_终稿.docx",
      "archive_chain": ["bundle.zip", "报告/inner.zip"],
      "file_type": "docx",
      "version_hints": ["终稿"],
      "metadata": {
        "title": "示例合同",
        "author": "李明",
        "modified": "2024-06-01T09:00:00Z",
        "page_count": 2
      }
    }
  ]
}
```

## 命令行参数

| 参数 | 含义 | 默认 |
| --- | --- | --- |
| `path` | `.zip`（或装了可选依赖的 `.rar` / `.7z`） |  |
| `-o, --output` | 写出的 manifest 路径；省略则打印到 stdout |  |
| `--max-depth` | 最多打开几层压缩包（含最外层） | 6 |
| `--max-uncompressed-bytes` | 累计解压字节上限 | 200 MiB |
| `--max-file-bytes` | 单个成员解压上限 | 50 MiB |
| `--max-files` | 最多处理的成员数 | 5000 |
| `--max-compression-ratio` | 超过该压缩比且体积达到阈值则跳过 | 100 |
| `--ratio-min-bytes` | 小于该体积的成员不做压缩比检查 | 1 MiB |

跳过的成员不会导致命令失败。真正读不了的输入（文件不存在、不是压缩包）退出码为 2。警告条数会写到标准错误。

## 限制

- ZIP 是完整路径。RAR 需要 `rar` extra 和系统 `unrar`；7z 需要 `py7zr` extra。未安装时，嵌套的 rar/7z 会留在清单里并写入 `warnings`，不会假装已经打开。
- 不做 OCR，不抽正文，不做向量化或 RAG。
- Word / PDF 只读廉价元数据。扫描件 PDF 的页数取决于文件里是否写了 `/Count`，加密或异常结构会得到 `null`。
- 中文文件名修复针对「未设置 UTF-8 标志、字节实为 GBK/GB18030」这一常见情况。已经标了 UTF-8 的名字按原样信任。不处理 Big5。启发式有可能误伤极少数 CP437 特殊文件名。
- 空文件哈希相同，但不会记成重复提示。
- 加密成员直接跳过。
- 这些上限是资源防护，不是恶意软件扫描。

## 许可证

MIT，见 [LICENSE](LICENSE)。
