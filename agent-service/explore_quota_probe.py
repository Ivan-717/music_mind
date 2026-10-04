"""实验：给「陌生歌手」留固定比例的位置。

【假设】冷启动零分是因为 artist 分量把 top-k 全导向了熟悉歌手，
而被藏的恰恰是陌生歌手。那就别让排序独占名额，按产品意图分配：
    k 个位置里，一部分给「你已经喜欢的」，一部分给「你还没听过的」
这是探索类产品的常规做法，不是为了让指标好看而调参。
"""
import sys
from musicmind_agent.db import get_connection
from musicmind_agent.evidence import load_all_enriched
from musicmind_agent.reco.score import build_profile, content_score
from musicmind_agent.reco.recall import recall, mmr
import musicmind_agent.evals.run_eval as R

QUOTA = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3

def recommend_with_quota(user_tracks, all_tracks, k):
    profile = build_profile(user_tracks)
    merged = list(recall(user_tracks, all_tracks, profile).values())
    ranked = mmr(merged, len(merged))

    new_slots = int(k * QUOTA)
    known_slots = k - new_slots
    known, new = [], []
    for item in ranked:
        (new if item.track.artist_id not in profile.known_artists else known).append(item)
    picked = known[:known_slots] + new[:new_slots]
    # 不够就互相补
    if len(picked) < k:
        rest = [x for x in ranked if x not in picked]
        picked += rest[:k - len(picked)]
    return [x.track.track_id for x in picked[:k]]

R.baselines.content = recommend_with_quota

for kind in ["artist_cold", "random_item"]:
    print(f"########## {kind}（陌生歌手配额 {QUOTA:.0%}）##########")
    sys.argv = ["run_eval", "--kind", kind, "--systems", "content,genre_prior",
                "--folds", "5", "--k", "50"]
    R.main()
    print()
