"""报告验收：只看文本字段，不碰 JSON 结构。"""
import json, re, sys
from musicmind_agent.db import get_connection
from musicmind_agent.evidence import resolve_user
from musicmind_agent.tools import build_context, call, core_tool_names

PLACEHOLDER = re.compile(r"\{([^{}]+)\}")

def walk_strings(node, path=""):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from walk_strings(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk_strings(v, f"{path}[{i}]")

def main(report_path, user_id):
    c = get_connection()
    ev = set(resolve_user(c, user_id).all_ids)
    ctx = build_context(c, user_id)
    for n in core_tool_names():
        call(n, ctx)
    facts = ctx.facts
    c.close()

    rep = json.load(open(report_path, encoding="utf-8"))
    r, u = rep["report"], rep["usage"]

    ph, bare = [], []
    for path, text in walk_strings(r):
        # 只关心叙事字段，metric_refs 的 key 本来就是引用不是文本
        if ".metric_refs" in path:
            continue
        for m in PLACEHOLDER.finditer(text):
            ph.append((path, m.group(1)))
        for n in re.findall(r"\d+(?:\.\d+)?%?", text):
            bare.append((path, n))

    bad_ev = [(d["dimension"], t) for d in r["dimensions"]
              for cl in d["claims"] for t in cl["evidence_track_ids"] if t not in ev]
    bad_an = [(x["track_id"], a) for x in r["recommendations"]
              for a in x["relation_to_history"]["anchors"] if a not in ev]
    bad_rc = [x["track_id"] for x in r["recommendations"] if x["track_id"] in ev]

    print(f"=== {report_path}  ({u['provider']}/{u['model']}) ===")
    print(f"  未渲染占位符      : {len(ph)} {ph[:4] if ph else '✓'}")
    fabricated = [k for _, k in ph if k not in facts]
    print(f"  其中编造的事实名  : {len(fabricated)} {fabricated if fabricated else '✓'}")
    print(f"  越界证据          : {len(bad_ev)} {bad_ev[:3] if bad_ev else '✓'}")
    print(f"  越界锚点          : {len(bad_an)} {bad_an[:3] if bad_an else '✓'}")
    print(f"  推荐用户已有的歌  : {len(bad_rc)} {bad_rc if bad_rc else '✓'}")
    print(f"  维度 {len(r['dimensions'])} / 推荐 {len(r['recommendations'])} / limitations {len(r['limitations'])}")
    print(f"  叙事里的裸数字    : {len(bare)} 处，例如 {bare[:4]}")

if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
