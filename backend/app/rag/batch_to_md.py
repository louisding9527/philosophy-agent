#!/usr/bin/env python3
"""批量转换文档为 Markdown（基于 microsoft/markitdown）。

用法:
    python batch_to_md.py <文件或目录>

行为:
    - 输入为目录: 递归转换其中所有文件, 输出到 <目录>/result, 保持相对目录结构
    - 输入为文件: 输出到 <所在目录>/result
    - result 里已存在同名 .md（不同扩展名转换而来）则跳过, 不重复转换
    - .md / .markdown 文件本身不转换
"""
import sys
from pathlib import Path

from markitdown import MarkItDown

SKIP_SUFFIX = {".md", ".markdown"}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    target = Path(sys.argv[1])
    if not target.exists():
        print(f"路径不存在: {target}", file=sys.stderr)
        return 1

    if target.is_file():
        root = target.parent
        files = [target]
    else:
        root = target
        files = [p for p in root.rglob("*") if p.is_file()]

    result_dir = root / "result"
    result_dir.mkdir(parents=True, exist_ok=True)

    converter = MarkItDown()
    converted = skipped = failed = 0

    for src in files:
        if src.suffix.lower() in SKIP_SUFFIX or result_dir in src.parents:
            continue

        out = result_dir / src.relative_to(root).with_suffix(".md")
        if out.exists():
            print(f"[跳过] 已转换: {src} -> {out}")
            skipped += 1
            continue

        try:
            text = converter.convert(str(src)).text_content
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            if not text.strip():
                print(f"[警告] 转换结果为空: {src}")
            else:
                print(f"[OK] {src} -> {out}")
            converted += 1
        except Exception as exc:
            failed += 1
            print(f"[失败] {src}: {exc}", file=sys.stderr)

    print(f"\n完成: 转换 {converted}, 跳过 {skipped}, 失败 {failed}")
    print(f"结果目录: {result_dir}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
