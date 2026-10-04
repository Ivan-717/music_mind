"""切分与天花板。

【切分必须版本化落盘】否则两次评估的结果没法比 —— 你不知道差异来自
算法改动还是来自换了一批藏歌。文件名带哈希，结果里记下用的是哪份。
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

SPLIT_DIR = Path(__file__).resolve().parent / "splits"
SEED = 20261003          # 固定种子 —— 评估必须可复现


@dataclass
class Fold:
    index: int
    hidden_ids: set[int]
    kind: str            # random_item / artist_cold

    def name(self) -> str:
        digest = hashlib.sha1(
            ",".join(map(str, sorted(self.hidden_ids))).encode()).hexdigest()[:8]
        return f"{self.kind}-f{self.index}-{digest}"


def random_item_folds(tracks, folds: int = 5) -> list[Fold]:
    """按曲目随机藏 20%。乐观值。"""
    rng = random.Random(SEED)
    ids = [t.track_id for t in tracks]
    rng.shuffle(ids)
    size = len(ids) // folds
    return [
        Fold(index=i, hidden_ids=set(ids[i * size:(i + 1) * size]), kind="random_item")
        for i in range(folds)
    ]


def artist_cold_folds(tracks, folds: int = 5) -> list[Fold]:
    """按艺人藏 —— 整个人的曲目全部藏起。真实泛化，主指标。

    【为什么不按行随机】按行随机会把同专辑/同艺人的近邻留在训练集里，
    推荐只要说「你听过周杰伦，再听一首周杰伦」就能命中 ——
    那测的是「同专辑近邻」，不是口味泛化。
    """
    rng = random.Random(SEED)
    by_artist: dict[int, list[int]] = {}
    for t in tracks:
        if t.artist_id:
            by_artist.setdefault(t.artist_id, []).append(t.track_id)

    artists = sorted(by_artist)
    rng.shuffle(artists)
    size = max(1, len(artists) // folds)
    return [
        Fold(index=i,
             hidden_ids={tid for a in artists[i * size:(i + 1) * size]
                         for tid in by_artist[a]},
             kind="artist_cold")
        for i in range(folds)
    ]


def ceiling(fold: Fold, all_tracks, profile_genres: set[str],
            profile_artists: set[int]) -> tuple[int, int]:
    """(可检索的藏歌数, 藏歌总数)。

    「可检索」的定义：库里存在一个【不在藏歌里】的候选，它和**这首藏歌**
    同流派（且那个流派也在用户的 top 里）或同艺人。

    【判据必须落在 target 上】第一版漏了这一点：条件写成了
    「候选池里有没有歌带用户的 top 流派」—— 那是在问「库里有没有流行歌」，
    几乎永远是「有」，于是天花板恒为 100%，指标失去意义。
    正确的问题是对**每首藏歌**问：「库里有和它像的东西吗」。

    实测（vdev, random-item，修好之后）：藏 89 首，天花板 89/89。

    【这个指标是诊断，不是修饰】
      · 天花板高 → 库里的同类足够，recall 低就是算法的问题
      · 天花板明显低 → 那些藏歌在库里根本没有同类，
                       任何算法都拿不回来，别算在算法头上
    """
    by_id = {t.track_id: t for t in all_tracks}
    pool = [t for t in all_tracks if t.track_id not in fold.hidden_ids]

    retrievable = 0
    for tid in fold.hidden_ids:
        target = by_id.get(tid)
        if target is None:
            continue
        target_genres = set(target.genres) & profile_genres    # 只在用户 top 里比
        if any(
            (set(o.genres) & target_genres)
            or (target.artist_id and o.artist_id == target.artist_id)
            for o in pool
        ):
            retrievable += 1
    return retrievable, len(fold.hidden_ids)


def save(fold: Fold, path: Path | None = None) -> Path:
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    path = path or SPLIT_DIR / f"{fold.name()}.json"
    path.write_text(json.dumps({
        "kind": fold.kind, "index": fold.index,
        "hidden_ids": sorted(fold.hidden_ids), "seed": SEED,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
