# M5.1 交接：按名字找维基条目

**这一步的 Python 归你写，我验收。** 它是 RAG 的**前置**，而且跟 RAG 本身无关 ——
解决的是仓库里那个已经踩了三次的名字匹配问题（这是第四次）。

---

## 为什么必须先做

调研时用 `titles=<名字>` 精确取，结果：

```
G.E.M. 鄧紫棋     中文 ✗  英文 ✗     ← 她那页肯定存在
contemporary r&b  中文 ✗  英文 ✗     ← 该是 "Contemporary R&B"
```

`titles=` 要求名字**精确对上**（重定向能救一部分，救不了全部）。
而这两个失败**不报错** —— 看起来就是「维基上没有这个人」。

**如果这一层不对，M5 抓下来的语料是按名字覆盖率打的折，而没人会发现。**

用 `list=search` 会宽容得多，但搜索自己的排序**不可信** —— 实测搜
「contemporary r&b」第一条可能是个音乐节。这正是仓库里 MusicBrainz 那个坑
的同一个形态（`score` 完全不可信，必须自己按名字筛）。

### 【2026-10-05 更正】不是「换成 search」，是**两条都要**

第一版规格写的是「从 `titles=` 换成 `search`」—— **只对了一半**，实测踩到了。

```
米津玄師  英文条目叫 Kenshi Yonezu     titles= 靠重定向能到（14241 字）
                                     search 也搜得到，但被「名字必须像」的档位判据拒了
BTS      中文条目叫「防弹少年团」       同上
```

`search` + 按名字筛**会把跨文字的别名全部丢掉**，而那些条目往往正是语料最厚的
（米津玄師 中文 3862 字 vs 英文 14241 字）。

**正确规则：每个语言先试 `titles=`（重定向是维基自己给的断言），空了再 `search` + 档位筛。**

改完之后头部 10 位从「单语言、10/10」变成「**中英双份、10/10**」，
语料厚度普遍翻 2-4 倍。

---

## 你要写的（2 个文件）

### 1. `agent-service/musicmind_agent/config.py` 加一行

```python
# Wikipedia。**和 MusicBrainz 一样，他们要求 UA 里带联系方式**
WIKI_USER_AGENT = os.getenv("WIKI_USER_AGENT") or MUSICBRAINZ_USER_AGENT
```

### 2. `agent-service/musicmind_agent/wiki.py` —— 新增

```python
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
        text = pages[0].get("extract") or ""
        # 【消歧义页要丢掉】它是一串条目名，对 RAG 毫无价值，
        # 而且会被当成「正文」灌进向量库
        if "可以指" in text[:120] or "may refer to" in text[:120]:
            return ""
        return text


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
            hit = pick_best(name, client.search(lang, name))
            if hit is None:
                continue
            text = client.extract(lang, hit["title"])
            if not text:
                continue
            out.append(WikiPage(lang=lang, title=hit["title"],
                                pageid=hit["pageid"], text=text))
        except WikiError:
            # 一个语言挂了不该把另一个也丢掉
            continue
    return out
```

### 3. `agent-service/tests/test_wiki.py` —— 新增

**离线的部分**（必须秒级、不联网）：

```python
"""维基条目查找的测试。

【联网的两个用例单独标】它们是真去查维基，用来钉住两个实测失败过的名字；
其余全离线 —— 混在一起的话没人愿意跑测试。
"""

from __future__ import annotations

import pytest

from musicmind_agent.wiki import pick_best


def cand(title, pageid=1, size=1000):
    return {"title": title, "pageid": pageid, "size": size}


def test_exact_match_wins():
    """搜索自己把「无关的」排在前面时，档位要能把它压回去。

    实测：搜一个流派名，第一条可能是个音乐节。
    """
    best = pick_best("contemporary r&b", [
        cand("Contemporary R&B", 2),
        cand("节奏布鲁斯音乐节", 3),
    ])
    assert best["title"] == "Contemporary R&B"


def test_ignores_spaces_and_punctuation_case():
    """「contemporary r&b」和「Contemporary R&B」是同一个东西。"""
    assert pick_best("contemporary r&b", [cand("Contemporary R&B")]) is not None


def test_traditional_simplified_both_ways():
    best = pick_best("林俊杰", [cand("林俊傑")])
    assert best is not None, "繁简没归一的话这个歌手永远找不到"


def test_partial_name_still_matches():
    """查询词里带着前缀时也要能找到 —— 「G.E.M. 鄧紫棋」对「鄧紫棋」。

    这是实测失败过的那个：`titles=` 精确取查不到她，而她的页就在那儿。
    """
    assert pick_best("G.E.M. 鄧紫棋", [cand("鄧紫棋")]) is not None


def test_unrelated_results_are_rejected():
    """**宁可返回空，也不要一个不像的。** 返回错条目的代价是往向量库里
    灌一篇讲别的东西的文章，而检索时它会以很高的相似度被捞出来。"""
    assert pick_best("薛之谦", [cand("香港"), cand("1997年")]) is None


def test_empty_candidates():
    assert pick_best("薛之谦", []) is None


@pytest.mark.network
@pytest.mark.parametrize("name", ["G.E.M. 鄧紫棋", "contemporary r&b", "林俊杰"])
def test_real_lookups(name):
    """真去查维基。钉住三个实测失败过的名字（前两个是名字匹配，
    第三个是繁简漏字）。跑法：pytest -m network"""
    from musicmind_agent.wiki import find_pages
    pages = find_pages(name)
    assert pages, f"{name} 一页都没找到"
    assert max(len(p.text) for p in pages) > 500
```

`pytest.ini` 里要加一个 marker（不然会有 warning）：

```ini
markers =
    network: 真的联网
```

---

## 验收

```bash
cd agent-service
# 离线部分必须秒级全绿
.venv/Scripts/python.exe -m pytest tests/test_wiki.py -q -m "not network"
# 联网的三个
.venv/Scripts/python.exe -m pytest tests/test_wiki.py -q -m network
```

**跑一遍真实覆盖率**（这个最有说服力，也是我调研时用的那套）：

```bash
.venv/Scripts/python.exe -c "
import sys; sys.stdout.reconfigure(encoding='utf-8'); sys.path.insert(0,'.')
from musicmind_agent.db import get_connection
from musicmind_agent.wiki import find_pages
c=get_connection(); cur=c.cursor()
cur.execute('''SELECT a.name, COUNT(*) n FROM track_artist ta JOIN artist a ON a.id=ta.artist_id
  GROUP BY a.id ORDER BY n DESC LIMIT 10''')
ok=tot=0
for r in cur.fetchall():
    pages=find_pages(r['name']); best=max((len(p.text) for p in pages), default=0)
    langs='/'.join(p.lang for p in pages) or '—'
    ok += 1 if best else 0; tot += 1
    print(f\"  {r['name'][:16]:16} {langs:6} {best:>7} 字\")
print(f'覆盖 {ok}/{tot}')
c.close()"
```

**期望看到**：之前 `titles=` 方法覆盖 9/10，现在应该 **10/10**，而且
G.E.M. 鄧紫棋 要出现。

---

## 坑

1. **不要信搜索的排序。** 拿回来必须按名字重排 —— 这是 MusicBrainz 那个坑的同一个形态
2. **宁可返回空，不要返回不像的。** 错条目的代价是往向量库灌一篇讲别的东西的文章，
   而它会在检索时以很高的相似度被捞出来 —— 那种错查不出来
3. **消歧义页要丢。** 它是一串条目名，正文开头是「可以指」/「may refer to」
4. **一个语言挂了不能把另一个也丢掉**（`find_pages` 里那个 try 就是干这个的）
5. **`titles=` 和 `list=search` 是两条路。** 前者要求精确，后者宽容但要自己筛。
   结论是「search + 自己筛」—— 这次实测出来的
