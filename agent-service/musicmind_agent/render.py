"""把报告里的「数字引用」换成真值，并校验引用本身。

【机制】LLM 写叙事时**不写数值**，写占位符：

    "你有 {genre.album.mandopop.share} 的歌是 mandopop"

渲染时替换成 68.3%。这样「编造一个数字」在结构上就写不出来 ——
不是靠事后扫描去抓，而是它根本没有地方写。

【为什么这条比「事后检查」强】事后检查总有漏网的写法（"三成"、"大约三分之二"、
"将近七成"）。结构上堵死之后，字面量扫描只需要处理 LLM 漏用占位符的情况，
而不是承担全部防线。
"""

from __future__ import annotations

import re
from typing import Any

# {genre.album.mandopop.share} / {artist.薛之谦.share} / {scope.tracks}
#
# 【必须是「不含花括号的任意字符」而不是 [a-zA-Z0-9_.]】
# 事实名里会带中文 —— artist_affinity 用艺人名生成 key（artist.薛之谦.share）。
# 写成 ASCII 字符集会【静默】漏掉这些（正则匹配不上 → 原样保留 → 报告里出现
# 一个没渲染的花括号），而不会报错。我第一版就是这样，
# 连验证脚本都用了同一个错正则，于是两边都看不见这个 bug。
PLACEHOLDER = re.compile(r"\{([^{}]+)\}")

# 哪些后缀按百分比渲染。share/ratio/lift 是比例语义，
# 写 0.683 没人看得懂，写 68.3% 才读得通
PERCENT_SUFFIXES = ("share", "ratio")

# 花括号里是纯数字的：{68.3%} / {95}
#
# 【这不是占位符，是模型的格式误解】实测：追问时它把「要提数字就写占位符」
# 理解成了「把数字包进花括号」，于是写出 `占 {68.3%}` ——
# 数字是对的（渲染前它引用了正确的键，替换后又被自己包了一层），但显示出来
# 带着花括号，用户会以为页面坏了。
#
# 只处理「纯数字」这一种：编造的事实名（{form.album.share}）里有点号和字母，
# 不会命中，照样被验证器抓出来。所以这个兜底不会掩盖真问题
# 注意 \s* 不能写进捕获组 —— 写进去的话 `{ 0.683 }` 会被替换成 `0.683 `
# （把空格一起带出来），而那个尾随空格会跑到句子里
BARE_VALUE = re.compile(r"\{\s*(\d+(?:\.\d+)?)\s*(%?)\s*\}")


class RenderError(Exception):
    pass


def format_metric(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        if key.endswith(PERCENT_SUFFIXES):
            return f"{value * 100:.1f}%"
        if key.endswith("lift"):
            return f"{value:.1f} 倍"
        return f"{value:.2f}"
    return str(value)


def render_text(text: str, facts: dict[str, Any], strict: bool = True) -> str:
    """把文本里的 {key} 换成真值。

    strict=True 时，引用一个不存在的 key 直接抛 —— 那说明 LLM 编了一个
    事实名，或者用了一个本轮没跑过的工具的输出。两种情况都必须让上层知道，
    不能渲染成空字符串蒙混过去（那会变成「你有  的歌是 mandopop」这种句子）。
    """
    # 【先剥掉「数字被包进花括号」的格式误解，再做占位符替换】
    # 顺序反了的话，strict 模式下 {68.3%} 会被当成「引用了不存在的键」抛异常 ——
    # 它根本不是键，是模型的格式误解（见 BARE_VALUE 的说明）。
    # 而 {form.album.share} 那种编造的键含点号和字母，不会被这一步碰到
    text = BARE_VALUE.sub(r"\1\2", text)

    missing: list[str] = []

    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in facts:
            missing.append(key)
            return match.group(0)
        return format_metric(key, facts[key])

    rendered = PLACEHOLDER.sub(replace, text)

    if missing and strict:
        raise RenderError(f"引用了不存在的事实：{missing}")

    return rendered


def find_bare_numbers(text: str) -> list[str]:
    """找出文本里没走占位符的裸数字。

    这是给验证器的「字面量层」用的：结构上堵死了编造数字，但 LLM 可能
    忘了用占位符而直接写「68.3%」。这种要能被发现，然后要么改成引用，
    要么由验证器核对它能不能对上某条事实。

    中文数字（三成、两首）不在这里处理 —— 那个归验证器，因为需要
    归一化之后再去 facts 里找匹配，逻辑比正则复杂。
    """
    without_placeholders = PLACEHOLDER.sub(" ", text)
    return re.findall(r"\d+(?:\.\d+)?%?", without_placeholders)


def verify_metrics(
    metric_refs: list[dict[str, Any]],
    facts: dict[str, Any],
    default_tol: float = 0.005,
) -> list[str]:
    """核对 metric_refs 里的每个引用。返回违规说明列表（空 = 通过）。

    LLM 可以显式给出 expect 值（它以为的数字），这里逐个核对。
    差超过容忍度说明它读错了数据 —— 这比它编一个数字更隐蔽，
    因为它确实引用了真实存在的事实名。
    """
    violations: list[str] = []
    for ref in metric_refs:
        key = ref.get("key")
        if key not in facts:
            violations.append(f"引用了不存在的事实：{key}")
            continue
        expect = ref.get("expect")
        if expect is None:
            continue
        actual = facts[key]
        tol = ref.get("tol", default_tol)
        if isinstance(actual, (int, float)) and isinstance(expect, (int, float)):
            if abs(float(actual) - float(expect)) > tol:
                violations.append(
                    f"{key}：报告里写 {expect}，实际是 {actual}（差超过 {tol}）"
                )
        elif actual != expect:
            violations.append(f"{key}：报告里写 {expect!r}，实际是 {actual!r}")
    return violations
