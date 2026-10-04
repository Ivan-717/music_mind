"""数字和名称的归一化。L3 / L4 的公共件。

【为什么要单独一个文件】「能不能绑到某条事实」这个判断在两个层里都要用，
而且它比看起来难：中文数字、百分比和小数、四舍五入、带千分位。
写两遍一定漂移，而漂移的表现是「同一个数字在一层能过、另一层过不了」。
"""

from __future__ import annotations

import re

from zhconv import convert

# 中文数字。只覆盖报告里实际会出现的量级 —— 没人会在乐评里写「三万两千首」
CN_DIGITS = {
    "零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# 「三成」「两首」「近一半」「三分之一」这类
CN_APPROX = {
    "一半": 0.5, "半": 0.5, "三分之一": 1 / 3, "四分之一": 0.25,
    "三成": 0.3, "四成": 0.4, "五成": 0.5, "六成": 0.6,
    "七成": 0.7, "八成": 0.8, "九成": 0.9,
}


def parse_cn_number(text: str) -> float | None:
    """把「三」「十」「十二」「二十」这类解析成数字。解析不了返回 None。"""
    if text in CN_APPROX:
        return CN_APPROX[text]
    if not text:
        return None
    if text == "十":
        return 10.0
    if text.endswith("十"):
        head = CN_DIGITS.get(text[:-1])
        return head * 10.0 if head is not None else None
    if "十" in text:
        head, tail = text.split("十", 1)
        h = CN_DIGITS.get(head) if head else 1
        t = CN_DIGITS.get(tail)
        if h is None or t is None:
            return None
        return h * 10.0 + t
    if len(text) == 1:
        value = CN_DIGITS.get(text)
        return float(value) if value is not None else None
    return None


def numeric_forms(value: float) -> set[str]:
    """一个数值在文本里可能长什么样。

    「能绑上」不是字符串相等 —— 0.6835 在报告里会写成 68.3%，也可能写成 68%、
    0.68。全部列出来，任何一个命中就算绑上了。
    """
    forms = {
        f"{value:.2f}", f"{value:.1f}", f"{value:.0f}",
        f"{value:.2%}", f"{value:.1%}", f"{value:.0%}",
        f"{value * 100:.2f}", f"{value * 100:.1f}", f"{value * 100:.0f}",
        f"{int(value)}" if value == int(value) else "",
    }
    return {f for f in forms if f}


NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?%?")


def extract_numbers(text: str) -> list[str]:
    return NUMBER_RE.findall(text or "")


def canonical(value: float, places: int = 2) -> str:
    return f"{round(value, places):.2f}"


def name_variants(text: str) -> set[str]:
    """繁简 + 空格 + 大小写归一。**这个仓库里凡是比名字的地方都要用它** ——
    已经在实体对齐和 iTunes 匹配上栽过两次，别再栽第三次。"""
    if not text:
        return set()
    base = text.replace(" ", "").lower()
    out = {base, convert(base, "zh-cn").replace(" ", "").lower(),
           convert(base, "zh-tw").replace(" ", "").lower()}
    return {o for o in out if o}


def name_matches(needle: str, haystack: str) -> bool:
    """needle 的任一繁简变体出现在 haystack 的任一变体里。两边都要展开。"""
    return any(n in h for n in name_variants(needle) for h in name_variants(haystack))