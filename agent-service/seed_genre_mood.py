"""流派 → 情绪（arousal / valence）的映射表。

用法：
    python seed_genre_mood.py --dry-run   # 只打印，给人 review
    python seed_genre_mood.py             # 写库

【为什么需要这张表】音频算得出能量，算不出效价 —— 实测《晴天》(伤感) 和
《小苹果》(欢快) 的音频 valence 完全分不开（见 audio/features.py 的说明）。
所以「正面/负面」这一维只能从流派推，标明是 inference 不是 measurement。

【这张表是整条链上唯一需要人工把关的地方】验证器能证明「报告里的数字来自
这张表」，证明不了「这张表是对的」。一旦写歪，所有情绪结论跟着歪。

【置信度不是装饰，是诚实】
    high    这个流派本身就带情绪倾向（ballad 就是慢和伤，dance-pop 就是快和亮）
    medium  倾向明显但有例外
    low     **这个流派太宽，横跨各种情绪**（mandopop 从抒情到舞曲全包），
            用它推情绪基本等于没推 —— 如实标出来，别假装有用

数值范围刻意和音频的 arousal 对齐（实测 0.04–0.87，均值 0.44），
这样两个来源的分数可以放在一起看，不会一个 0-1 一个 0-100。
"""

from __future__ import annotations

import argparse
import sys

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from musicmind_agent.db import get_connection  # noqa: E402

MAPPING_VERSION = "curated-1.0"

# name: (arousal, valence, confidence, 依据)
MAPPING: dict[str, tuple[float, float, str, str]] = {

    # ---- 华语区（占这个库的大头）----
    "ballad":               (0.22, 0.32, "high",   "慢速抒情，通常是失恋/怀念题材"),
    "mandopop":             (0.50, 0.50, "low",    "从抒情到舞曲全覆盖，单看它推不出情绪"),
    "cantopop":             (0.45, 0.45, "low",    "同上，粤语流行同样跨度极大"),
    "c-pop":                (0.48, 0.50, "low",    "同上"),
    "zhongguo feng":        (0.40, 0.45, "medium", "五声音阶、中慢板居多，偏含蓄"),
    "campus folk":          (0.32, 0.55, "medium", "校园民谣，清淡怀旧"),
    "oriental ballad":      (0.25, 0.35, "medium", "东方抒情，慢而感伤"),
    "singer-songwriter":    (0.40, 0.45, "low",    "是身份不是风格，跨度太大"),

    # ---- 说唱 / 节奏 ----
    "hip hop":              (0.70, 0.45, "medium", "节奏强，情绪中性偏冷"),
    "pop rap":              (0.70, 0.50, "medium", "流行化的说唱，比纯 hip hop 亮"),
    "trap":                 (0.75, 0.40, "medium", "重低音 + 快 hi-hat，常偏暗"),
    "emo rap":              (0.55, 0.25, "high",   "名字里就写着，低效价是定义的一部分"),
    "cloud rap":            (0.45, 0.35, "medium", "氛围化、飘忽，偏低能量"),
    "conscious hip hop":    (0.65, 0.40, "medium", "议题严肃，效价偏低"),
    "east coast hip hop":   (0.70, 0.45, "medium", "老派东岸，节奏扎实"),
    "gangsta rap":          (0.75, 0.30, "medium", "强硬、阴暗"),
    "drill":                (0.78, 0.28, "medium", "比 trap 更冷更暗"),

    # ---- 流行 ----
    "pop":                  (0.60, 0.60, "low",    "最宽的一个词，覆盖一切"),
    "dance-pop":            (0.80, 0.75, "high",   "为舞池写的，快且亮"),
    "synth-pop":            (0.62, 0.65, "medium", "合成器音色，明亮"),
    "teen pop":             (0.72, 0.78, "medium", "青春、明亮"),
    "alternative pop":      (0.55, 0.50, "medium", "比主流流行暗一点、怪一点"),
    "j-pop":                (0.65, 0.65, "medium", "编曲密度高，整体偏明亮"),
    "k-pop":                (0.72, 0.70, "medium", "制作精良、节奏强，偏正面"),
    "city pop":             (0.58, 0.68, "medium", "都市夜晚感，明亮松弛"),

    # ---- 摇滚 ----
    "rock":                 (0.75, 0.50, "low",    "跨度大，从柔情摇滚到硬摇滚"),
    "pop rock":             (0.72, 0.58, "medium", "旋律化的摇滚，比硬摇滚亮"),
    "alternative rock":     (0.72, 0.45, "medium", "常有阴郁底色"),
    "j-rock":               (0.78, 0.50, "medium", "能量高，情绪起伏大"),
    "hard rock":            (0.82, 0.50, "medium", "高能量"),
    "glam rock":            (0.78, 0.62, "medium", "华丽、张扬"),
    "folk rock":            (0.55, 0.55, "medium", "民谣底色 + 摇滚编制"),

    # ---- 灵魂 / R&B ----
    "contemporary r&b":     (0.48, 0.55, "medium", "中速律动，情绪偏暖"),
    "r&b":                  (0.48, 0.55, "medium", "同 contemporary r&b"),
    "alternative r&b":      (0.42, 0.40, "medium", "比主流 R&B 暗和实验"),
    "soul":                 (0.52, 0.62, "medium", "温暖、饱满"),
    "pop soul":             (0.55, 0.65, "medium", "流行化的灵魂乐，明亮"),
    "neo soul":             (0.45, 0.58, "medium", "松弛、温暖"),
    "trap soul":            (0.55, 0.40, "medium", "说唱节奏 + 灵魂旋律，偏暗"),

    # ---- 电子 ----
    "electronic":           (0.78, 0.58, "medium", "高能量，效价取决于子类型"),
    "edm":                  (0.85, 0.70, "high",   "为高潮段落写的"),
    "house":                (0.75, 0.68, "medium", "四拍律动，偏正面"),
    "deep house":           (0.65, 0.60, "medium", "比 house 沉，偏内敛"),
    "dubstep":              (0.82, 0.45, "medium", "重低音冲击，偏暗"),
    "melodic dubstep":      (0.72, 0.50, "medium", "dubstep 的旋律化分支，没那么凶"),
    "future bass":          (0.70, 0.65, "medium", "明亮、甜"),
    "trance":               (0.80, 0.68, "medium", "持续高能，上扬"),
    "downtempo":            (0.30, 0.48, "medium", "慢速氛围"),
    "ambient pop":          (0.28, 0.52, "medium", "氛围化，低能量"),
    "electropop":           (0.72, 0.68, "medium", "电子化的流行，明亮"),

    # ---- 民谣 ----
    "folk":                 (0.35, 0.50, "medium", "原声为主，情绪平和"),
    "folk pop":             (0.42, 0.55, "medium", "流行化的民谣，偏暖"),
    "contemporary folk":    (0.35, 0.48, "medium", "当代民谣，常有忧郁底色"),
    "indie folk":           (0.32, 0.42, "medium", "独立民谣，偏低落"),
    "alternative folk":     (0.35, 0.45, "medium", "同 indie folk"),

    # ---- 爵士 ----
    "jazz":                 (0.52, 0.62, "low",    "从慵懒到激烈都有"),
    "vocal jazz":           (0.48, 0.65, "medium", "人声爵士，温暖"),
    "swing":                (0.68, 0.75, "high",   "摇摆乐，为跳舞和欢快而生"),
    "big band":             (0.65, 0.72, "medium", "大乐队编制，热烈"),
    "gypsy jazz":           (0.70, 0.70, "medium", "快速、欢快"),
    "bossa nova":           (0.35, 0.62, "medium", "慵懒、柔和、偏暖"),

    # ---- 古典（这一组的置信度整体偏低：跨度太大）----
    "classical":            (0.45, 0.50, "low",    "五百年跨度，从安魂曲到圆舞曲"),
    "baroque":              (0.50, 0.58, "medium", "结构规整，情绪克制偏明朗"),
    "romantic classical":   (0.45, 0.42, "low",    "浪漫主义从狂喜到绝望都有"),
    "concerto":             (0.55, 0.55, "low",    "协奏曲快慢乐章差别极大"),
    "oratorio":             (0.45, 0.45, "low",    "宗教体裁，庄严"),
    "opera":                (0.55, 0.40, "low",    "从喜剧到悲剧都有"),
    "chamber pop":          (0.45, 0.50, "medium", "室内乐编制 + 流行旋律，精致"),
    "theme and variations": (0.45, 0.50, "low",    "曲式不是风格，推不出情绪"),
    "christmas music":      (0.60, 0.78, "high",   "节日音乐，明确欢快"),
    "gospel":               (0.62, 0.75, "medium", "宗教赞美，高扬"),
    "church music":         (0.35, 0.55, "medium", "教堂音乐，肃穆平和"),

    # ---- 其他 ----
    "instrumental":         (0.50, 0.50, "low",    "只是说没有唱，和情绪无关"),
    "acoustic":             (0.35, 0.55, "medium", "原声编制，朴素"),
    "lo-fi":                (0.28, 0.48, "medium", "低传真正在营造放松感"),
    "chillout":             (0.25, 0.60, "medium", "为放松而作"),
    "comedy":               (0.60, 0.75, "medium", "喜剧音乐，轻松"),
    "comedy rock":          (0.68, 0.72, "medium", "搞笑摇滚，能量高且正面"),
    "aor":                  (0.62, 0.68, "medium", "成人抒情摇滚，明亮顺耳"),
    "disco":                (0.82, 0.80, "high",   "为舞池而生，快且欢快"),
    "euro-disco":           (0.82, 0.78, "high",   "同 disco"),
    "funk":                 (0.78, 0.72, "high",   "律动强，欢快"),
    "boogie-woogie":        (0.80, 0.75, "high",   "快速布鲁斯，欢腾"),
    "blues":                (0.45, 0.32, "medium", "忧郁是它的定义"),
    "country":              (0.55, 0.58, "medium", "叙事性，情绪平和偏暖"),
    "country pop":          (0.60, 0.65, "medium", "流行化的乡村，明亮"),
    "contemporary country": (0.58, 0.60, "medium", "当代乡村"),
    "latin disco":          (0.82, 0.78, "medium", "拉丁舞曲，热烈"),
    "psytrance":            (0.85, 0.60, "medium", "迷幻 trance，持续高压"),
    "drum and bass":        (0.85, 0.55, "medium", "极快节奏"),
    "crust punk":           (0.90, 0.30, "medium", "极端朋克，高能且愤怒"),
    "thrash metal":         (0.90, 0.35, "medium", "激流金属，快而攻击性强"),
    "death metal":          (0.92, 0.25, "medium", "极端金属，最暗最猛"),
    "trap metal":           (0.85, 0.28, "medium", "说唱 + 金属，阴沉"),
    "trap edm":             (0.82, 0.55, "medium", "电子化的 trap"),
    "new wave":             (0.65, 0.58, "medium", "新浪潮，冷感但有劲"),
    "dance":                (0.80, 0.72, "medium", "为跳舞而作"),
    "club":                 (0.82, 0.72, "medium", "俱乐部音乐"),
    "production music":     (0.50, 0.50, "low",    "罐头音乐，为画面服务，不表达情绪"),
    "min'yō":               (0.50, 0.50, "medium", "日本民谣"),
    "ryūkōka":              (0.45, 0.40, "medium", "昭和歌谣，常有感伤底色"),
    "ballet":               (0.45, 0.50, "low",    "体裁不是风格"),
    "cantata":              (0.45, 0.50, "low",    "同上"),
    "mass":                 (0.35, 0.50, "medium", "弥撒曲，肃穆"),
    "motet":                (0.35, 0.50, "medium", "经文歌，肃穆"),
    "sonata":               (0.45, 0.50, "low",    "曲式不是风格"),
    "symphony":             (0.50, 0.45, "low",    "交响曲跨度极大"),
    "modern classical":     (0.40, 0.35, "low",    "现代古典常刻意不悦耳"),
    "jazz blues":           (0.50, 0.38, "medium", "爵士化的布鲁斯，忧郁底色"),
    "piano blues":          (0.42, 0.35, "medium", "钢琴布鲁斯，低沉"),
    "smooth soul":          (0.45, 0.65, "medium", "顺滑温暖"),
    "deep soul":            (0.48, 0.50, "medium", "深灵魂，情感浓烈"),
    "southern soul":        (0.55, 0.62, "medium", "南方灵魂，温暖有劲"),
    "hip hop soul":         (0.58, 0.55, "medium", "说唱 + 灵魂"),
    "southern hip hop":     (0.75, 0.50, "medium", "南方说唱，节奏厚重"),
    "new york drill":       (0.78, 0.28, "medium", "纽约 drill，冷硬"),
    "chicago drill":        (0.78, 0.28, "medium", "同 drill"),
    "chipmunk soul":        (0.60, 0.58, "medium", "采样提速的灵魂乐，明亮"),
    "horrorcore":           (0.80, 0.20, "high",   "恐怖说唱，刻意阴暗"),
    "experimental hip hop": (0.60, 0.45, "low",    "实验性，什么都可能有"),
    "christian hip hop":    (0.68, 0.70, "medium", "宗教题材说唱，正面"),
    "melodic bass":         (0.75, 0.55, "medium", "旋律化低音音乐"),
    "korean ballad":        (0.25, 0.32, "high",   "韩式抒情，慢而感伤"),
    "traditional pop":      (0.50, 0.62, "medium", "传统流行，温和"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="写流派情绪映射表")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写库")
    args = parser.parse_args()

    connection = get_connection()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS `genre_mood` (
              `genre_id` bigint unsigned NOT NULL,
              `arousal` decimal(3,2) NOT NULL COMMENT '能量 0-1，取自流派倾向。【inference，不是实测】',
              `valence` decimal(3,2) NOT NULL COMMENT '效价 0-1，0=负面 1=正面。音频算不出这一维，只能从流派推',
              `confidence` varchar(8) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'high/medium/low。low=这个流派太宽，推不出情绪',
              `note` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '一句话依据，给人 review 用',
              `source` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '映射表版本',
              `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (`genre_id`),
              CONSTRAINT `fk_gm_genre` FOREIGN KEY (`genre_id`) REFERENCES `genre` (`id`) ON DELETE CASCADE ON UPDATE RESTRICT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
              COMMENT='流派→情绪映射（人工 review 过的推断值，不是实测）'
            """
        )
        cursor.execute("SELECT id, name FROM genre")
        genre_ids = {row["name"]: row["id"] for row in cursor.fetchall()}

    missing = [name for name in MAPPING if name not in genre_ids]
    if missing:
        print(f"⚠ 库里没有这些流派（拼写不一致？）：{missing}")

    rows = 0
    for name, (arousal, valence, confidence, note) in sorted(MAPPING.items()):
        genre_id = genre_ids.get(name)
        if genre_id is None:
            continue
        rows += 1
        if args.dry_run:
            bar = "█" * int(arousal * 20)
            print(f"{name:24} 能量{arousal:.2f} 效价{valence:.2f} {confidence:6} {bar:22} {note}")
        else:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO genre_mood (genre_id, arousal, valence, confidence, note, source)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        arousal = VALUES(arousal), valence = VALUES(valence),
                        confidence = VALUES(confidence), note = VALUES(note),
                        source = VALUES(source)
                    """,
                    (genre_id, arousal, valence, confidence, note, MAPPING_VERSION),
                )
            connection.commit()

    if not args.dry_run:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT confidence, COUNT(*) n FROM genre_mood GROUP BY confidence"
            )
            print("已写入 genre_mood:", cursor.fetchall())
    connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
