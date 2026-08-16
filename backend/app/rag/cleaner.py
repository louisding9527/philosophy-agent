"""入库前文本校验与清洗：保证进分块器的文本源头干净。

在 load_file 之后、chunk_document 之前调用。只做无损清洗（不改文意），
校验不过的文档标记 invalid，由 pipeline 跳过入库并记录原因。
"""

import re
from dataclasses import dataclass, field

# markdown 纯链接行（epub 转换残留的目录项，如 [前言](part0005.html#A1-...)）
_LINK_LINE = re.compile(r"^\s*\[[^\]]*\]\([^)]*\)\s*$")
# markdown 纯图片行（如 ![0001-01](../images/00003.jpeg)）
_IMAGE_LINE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")
# markitdown 元信息行（文件头的 **Title:** / **Authors:** 等）
_METADATA_LINE = re.compile(r"^\*\*[^*]+:\*\*")

MIN_TEXT_LENGTH = 20  # 清洗后低于该长度视为不洁净（空/只剩噪音）
# 控制字符黑名单：保留 \n \t，其余全部剔除（含 null 字节）
_CONTROL_CHARS = dict.fromkeys(
    i for i in range(32) if i not in (9, 10)
)
# 零宽与 BOM 字符
_ZERO_WIDTH = dict.fromkeys(
    ord(ch) for ch in ("\ufeff", "\u200b", "\u200c", "\u200d", "\u2060")
)


@dataclass
class CleanResult:
    """一次清洗校验的结果。"""

    text: str  # 清洗后的文本；valid=False 时为空
    removed_lines: int = 0  # 剔除的噪音行数（链接/图片/元信息）
    warnings: list[str] = field(default_factory=list)
    valid: bool = True


def clean_text(raw: str) -> CleanResult:
    """校验并清洗原始文本，返回清洗结果。

    清洗步骤：去 BOM 与零宽字符 → 换行归一（\\r\\n/\\r → \\n）→ 去控制字符
    → 剔除纯链接/图片/元信息噪音行。校验：清洗后过短视为不洁净；
    乱码疑似（替换符占比异常、中文语料 CJK 占比过低）打 warning 不阻断。
    """
    text = raw.translate(_ZERO_WIDTH).translate(_CONTROL_CHARS)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    kept: list[str] = []
    removed = 0
    for line in lines:
        if _LINK_LINE.match(line) or _IMAGE_LINE.match(line):
            removed += 1
            continue
        # 文件头元信息块（连续行），正文中的 **加粗** 行不受影响
        if kept == [] and _METADATA_LINE.match(line):
            removed += 1
            continue
        kept.append(line)
    text = "\n".join(kept).strip()

    warnings: list[str] = []
    if len(text) < MIN_TEXT_LENGTH:
        return CleanResult(
            text="",
            removed_lines=removed,
            warnings=["文本过短（清洗后不足 20 字），跳过入库"],
            valid=False,
        )

    replacement_ratio = text.count("\ufffd") / max(len(text), 1)
    if replacement_ratio > 0.001:
        warnings.append(f"含替换符（U+FFFD）比例 {replacement_ratio:.2%}，疑似乱码")

    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if cjk / max(len(text), 1) < 0.2:
        warnings.append(f"CJK 占比 {cjk / max(len(text), 1):.0%} 过低，疑似非中文语料或乱码")

    return CleanResult(text=text, removed_lines=removed, warnings=warnings)
