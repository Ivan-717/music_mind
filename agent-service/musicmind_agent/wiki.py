"""按名字找维基条目，取正文。

【这一步解决什么】`titles=` 精确取会把「G.E.M. 鄧紫棋」「contemporary r&b」
这类名字全部漏掉，而**不报错** —— 看起来就是「维基上没有」。
改用 `list=search` 宽容地找，再自己按名字筛一遍。

【为什么不能直接取搜索结果的第一条】搜索的排序是它自己的相关度
（掺了链接数、页面大小），实测搜一个流派名，第一条可能是个音乐节。
**和 MusicBrainz 那个坑一样：score 不可信。** 所以 candidates 拿回来之后
必须按名字贴合度重排，对不上的宁可返回空。

【和 validate/normalize 的关系】名字归一化只有一份实现（`name_variants`：
繁简双向 + 去空格 + 小写）。这里直接用它，不另写一套 ——
另写的那套迟早和验证器 L4 实体层的判据漂移。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from musicmind_agent.config import WIKI_USER_AGENT
from musicmind_agent.validate.normalize import name_matches, name_variants

# 两次请求之间歇一下。维基没有 MusicBrainz 那种硬性 1 req/s，
# 但批量抓的时候还是客气点（一次抓 800 多个条目）
MIN_INTERVAL = 0.3
SEARCH_LIMIT = 5


class WikiError(Exception):
    pass


def _clean_extract(text: str) -> str:
    """正文的清洗。两条路（by_title / extract）共用 —— 写两份迟早漂移。

    【消歧义页要丢掉】它是一串条目名，对 RAG 毫无价值，
    而且会被当成「正文」灌进向量库，检索时以很高的相似度被捞出来。
    """
    if not text:
        return ""
    head = text[:120]
    if "可以指" in head or "可以指向" in head or "may refer to" in head:
        return ""
    return text


@dataclass
class WikiPage:
    lang: str          # zh / en
    title: str         # 条目名（重定向之后的）
    pageid: int
    text: str          # 纯文本正文

    @property
    def url(self) -> str:
        return f"https://{self.lang}.wikipedia.org/wiki/{self.title.replace(' ', '_')}"


class WikiClient:
    def __init__(self, timeout: int = 20, max_retries: int = 2,
                 min_interval: float = MIN_INTERVAL):
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": WIKI_USER_AGENT})
        self._last = 0.0

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)

    def _get(self, lang: str, params: dict) -> dict:
        params = {**params, "format": "json", "formatversion": 2}
        for attempt in range(self.max_retries + 1):
            self._wait()
            try:
                resp = self.session.get(
                    f"https://{lang}.wikipedia.org/w/api.php",
                    params=params, timeout=self.timeout)
                self._last = time.monotonic()
            except Exception as e:
                if attempt == self.max_retries:
                    raise WikiError(f"{type(e).__name__}: {e}") from e
                time.sleep(1.5 * (attempt + 1))
                continue

            if resp.status_code == 429:        # 太频繁，退避重试
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise WikiError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json()
        raise WikiError("重试完了还是失败")

    # ----------------------------------------------------------

    def search(self, lang: str, query: str, limit: int = SEARCH_LIMIT) -> list[dict]:
        """返回 [{title, pageid, size}]。**顺序是维基自己的，不要信。**"""
        data = self._get(lang, {
            "action": "query", "list": "search",
            "srsearch": query, "srlimit": limit, "srnamespace": 0,
        })
        return [
            {"title": r.get("title"), "pageid": r.get("pageid"),
             "size": r.get("size") or 0}
            for r in data.get("query", {}).get("search", [])
        ]

    def extract(self, lang: str, title: str) -> str:
        """取纯文本正文。消歧义页和空页返回空串。"""
        data = self._get(lang, {
            "action": "query", "prop": "extracts", "explaintext": 1,
            "redirects": 1, "titles": title,
        })
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return ""
        return _clean_extract(pages[0].get("extract") or "")

    def by_title(self, lang: str, name: str) -> "WikiPage | None":
        """按精确标题取，**跟着重定向走**。

        【为什么这条路不能省】维基的重定向能吃掉**跨文字的别名**：

            米津玄師  →  Kenshi Yonezu   （英文条目，14241 字）
            BTS       →  防弹少年团       （中文条目）

        这些条目往往正是语料最厚的（米津玄師 中文只有 3862 字）。
        而 `search` 虽然也能把它们搜出来，**按名字筛的那一层会把罗马字/译名拒掉** ——
        「名字必须像」这条规矩本身是对的，错的是拿它去筛所有的路。

        重定向是维基自己给的断言（「这两个名字是同一个东西」），比我们猜得准。
        所以：这条先试，空了再用 search。
        """
        data = self._get(lang, {
            "action": "query", "prop": "extracts", "explaintext": 1,
            "redirects": 1, "titles": name,
        })
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return None
        page = pages[0]
        text = _clean_extract(page.get("extract") or "")
        if not text:
            return None
        return WikiPage(lang=lang, title=page.get("title") or name,
                        pageid=page.get("pageid") or 0, text=text)


def pick_best(query: str, candidates: list[dict]) -> dict | None:
    """从搜索结果里挑最贴合查询词的那个。**不信搜索的排序。**

    贴合度分三档：
        3  是同一个名字的不同写法     薛之谦 / 薛之謙
        2  条目名出现在查询词里       查询「周杰倫 晴天」，条目「周杰倫」
        1  查询词出现在条目名里       查询「G.E.M. 鄧紫棋」，条目「鄧紫棋」
        0  不像                      → 不要

    【第 3 档为什么比的是「变体集合有没有交集」】不能拿归一化后的字符串比相等 ——
    「林俊杰」的变体是 {林俊杰, 林俊傑}，「林俊傑」的也是这两个，**有交集**；
    但它们的字符串本身不相等（繁简不同）。所以判据是集合相交，不是字符串相等。

    【为什么要分档而不是「能匹配就取第一条」】搜索会返回一堆沾边的，
    先按档再按维基自己的顺序，比反过来可靠 —— 档位是我们能解释的。
    """
    def same_name(a: str, b: str) -> bool:
        """同一个名字的两种写法（繁简 / 空格 / 大小写）。"""
        return bool(name_variants(a) & name_variants(b))

    best, best_rank = None, 0
    for cand in candidates:
        title = cand.get("title") or ""
        if not title:
            continue
        if same_name(query, title):
            rank = 3
        elif name_matches(title, query):     # 条目名 ⊂ 查询词
            rank = 2
        elif name_matches(query, title):     # 查询词 ⊂ 条目名
            rank = 1
        else:
            rank = 0
        if rank > best_rank:
            best, best_rank = cand, rank
    return best


def find_pages(name: str, langs: tuple[str, ...] = ("zh", "en"),
               client: WikiClient | None = None) -> list[WikiPage]:
    """两个语言各找一页。找不到的语言直接跳过（不是错误）。

    【为什么两个都找、不「中文优先」就完事】实测英文条目普遍比中文长
    一个数量级（周杰倫 1.2 万字 vs 5.1 万字），但中文条目更贴近中文读者。
    返回两边让调用方决定 —— M5.2 落盘时可以两个都存、打语言标记。
    """
    client = client or WikiClient()
    out: list[WikiPage] = []
    for lang in langs:
        try:
            # ① 精确标题 + 重定向。能吃跨文字的别名（米津玄師 → Kenshi Yonezu）
            page = client.by_title(lang, name)
            # ② 搜 + 按名字筛。吃的是「名字写得不全对」的情况
            #    （G.E.M. 鄧紫棋、contemporary r&b）
            if page is None:
                hit = pick_best(name, client.search(lang, name))
                if hit is not None:
                    text = client.extract(lang, hit["title"])
                    if text:
                        page = WikiPage(lang=lang, title=hit["title"],
                                        pageid=hit["pageid"], text=text)
            if page is not None:
                out.append(page)
        except WikiError:
            # 一个语言挂了不该把另一个也丢掉
            continue
    return out