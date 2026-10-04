"""实验：把流派【推断】的能量当实测塞进候选，看冷启动分数动不动。

【为什么值得先做这个】补真音频要 3-4 小时。如果连流派推断的能量
（和真实能量高度相关）都不能让冷启动回暖，那真音频大概率也不行 ——
先用 2 分钟证伪，再决定要不要花那 4 小时。
"""
import sys
from musicmind_agent.db import get_connection
from musicmind_agent.tools import load_mood_map
import musicmind_agent.evals.run_eval as R

connection = get_connection()
mood_map = load_mood_map(connection)
connection.close()

original = R.load_all_enriched
filled = {"n": 0, "no_genre": 0}

def patched(conn):
    tracks = original(conn)
    for t in tracks:
        if t.arousal_measured is not None:
            continue
        entries = [mood_map[g] for g in t.genres if g in mood_map]
        if not entries:
            filled["no_genre"] += 1
            continue
        wsum = sum(e["weight"] for e in entries)
        t.arousal_measured = sum(e["arousal"] * e["weight"] for e in entries) / wsum
        filled["n"] += 1
    return tracks

R.load_all_enriched = patched

sys.argv = ["run_eval", "--kind", sys.argv[1] if len(sys.argv) > 1 else "artist_cold",
            "--systems", "content,genre_prior", "--folds", "5", "--k", "50"]
R.main()
print(f"\n【注入统计】填了 {filled['n']} 首的推断能量，{filled['no_genre']} 首连流派都没有")
