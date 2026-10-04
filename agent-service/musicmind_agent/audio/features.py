"""从 30 秒音频片段算特征，合成音乐能量（arousal）。

【这一层是纯函数】不碰网络、不碰数据库。输入 numpy 波形，输出一个 dataclass。
这样它能被单测覆盖，也能被离线评估复用 —— 后面 reco 的打分函数要用同一套。

【为什么可以自己做】Spotify 的 audio-features 端点 2024-11 对新应用停了，
AcousticBrainz 冻结在 2022-07，Apple Music API 明确缺 energy 和 valence。
而 Spotify 当年算这些用的就是「30 秒片段 + 信号处理」—— 我们手里正好有
iTunes 的 30 秒 preview。所以自己算，不依赖任何人的 API。

【诚实的边界：只出能量，不出效价 —— 全部是实测得出的】
  · arousal（能量）站得住。测试集上的表现：
        说唱/摇滚   双截棍 0.674 / 经济舱 0.604 / 沧海一声笑 0.500
        抒情       十年 0.417 / 演员 0.389
    三个分量（RMS / spectral centroid / zcr）在两类之间有清晰间隔。
  · tempo 有倍频歧义。librosa 对无强鼓点的歌会把八分音符当拍 ——
    实测《演员》被估成 184.6 BPM（折半 92.3 才对）。所以它不参与 arousal。
  · valence 做不出来，已放弃（详见 AudioFeature 的说明）：
    伤感歌和欢快歌的 valence 完全混在一起。不再产这个数字。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import librosa
import numpy as np

# 特征算法版本。换算法/改归一化区间时必须升版本，否则新旧数据混在一张表里
# 分不出来，而「同一维度两套口径」是评估里最难查的一类脏数据
ANALYZER_VERSION = "1.0.0"

SAMPLE_RATE = 22050

# ---------------------------------------------------------------
# 归一化参考区间
#
# 【为什么用固定区间而不是按批次的百分位】跨批次可比。按百分位归一的话，
# 今天跑 100 首和明天跑 500 首得到的 0.8 不是同一个意思，评估就没法跨运行对比。
# 区间由实测标定：见文件头的数字
# ---------------------------------------------------------------
RANGES = {
    "rms": (0.05, 0.45),
    "spectral_centroid": (800.0, 4000.0),
    "zero_crossing_rate": (0.02, 0.20),
}

# arousal 三个分量的权重。
# 【tempo 不在里面】它有倍频歧义（见文件头），拿它参与合成等于往信号里掺噪声。
# 三个分量都在实测里显示出了区分度，权重按区分度大小排
AROUSAL_WEIGHTS = {
    "rms": 0.5,
    "spectral_centroid": 0.3,
    "zero_crossing_rate": 0.2,
}

# Krumhansl-Schmuckler 调性模板
_MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
_MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.5
    return clamp01((value - low) / (high - low))


def fold_tempo(bpm: float) -> float | None:
    """把 beat_track 的结果折进 [60, 160)。

    librosa 在没有强鼓点的歌上会把拍算成八分音符甚至十六分音符。
    实测《演员》（慢抒情）被估成 184.6 BPM —— 折半后 92.3 才合理。
    这是 beat tracking 的已知失效模式，不是这首歌真的那么快。
    """
    if not bpm or bpm <= 0 or math.isnan(bpm):
        return None
    while bpm >= 160:
        bpm /= 2
    while bpm < 60:
        bpm *= 2
    return bpm


def estimate_mode(y: np.ndarray, sr: int, windows: int = 8) -> tuple[bool | None, float]:
    """估计大调/小调。返回 (是否大调, 置信度 0-1)。

    【为什么要窗口投票】整曲平均 chroma 做一次匹配误差很大 ——
    实测《双截棍》被判成大调。切窗口各自投票更接近真实调性，
    因为局部和声比全局平均更能代表这首歌的调。
    """
    if len(y) < sr:                       # 不足一秒，别硬算
        return None, 0.0

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    if chroma.shape[1] < windows * 2:
        chunks = [chroma.mean(axis=1)]
    else:
        chunks = [c.mean(axis=1) for c in np.array_split(chroma, windows, axis=1)]

    votes_major = 0
    margins: list[float] = []

    for chunk in chunks:
        std = chunk.std()
        if std < 1e-9:                     # 一段静音或单音，投了也是噪声
            continue
        normalized = (chunk - chunk.mean()) / std

        best_major = max(
            float(np.corrcoef(normalized, np.roll(_MAJOR_PROFILE, i))[0, 1])
            for i in range(12)
        )
        best_minor = max(
            float(np.corrcoef(normalized, np.roll(_MINOR_PROFILE, i))[0, 1])
            for i in range(12)
        )

        if best_major >= best_minor:
            votes_major += 1
        margins.append(abs(best_major - best_minor))

    valid = len(margins)                  # 静音/单音窗口不投票，也不进分母
    if valid == 0:
        return None, 0.0

    is_major = votes_major * 2 >= valid
    majority = max(votes_major, valid - votes_major) / valid
    # 置信度 = 投票一致性 × 平均领先幅度（两者都高才算真的分得清）
    confidence = clamp01(majority * clamp01(float(np.mean(margins)) / 0.15))
    return is_major, confidence


@dataclass
class AudioFeature:
    """一首歌的音频特征。字段名和 track_audio_feature 表一一对应。

    【这里没有 valence，是实测逼出来的决定】
    本来按计划要合成 valence，测试集上完全失败：

        晴天(伤感)   valence 0.780      ← 比下面那首还「欢快」
        告白气球(轻快) valence 0.728
        小苹果(欢快)  valence 0.669
        十年(伤感)   valence 0.669

    伤感歌和欢快歌混在一起，没有分辨力。原因有两个，都不是能靠调参解决的：
      · Krumhansl 匹配有关系调歧义（C 大调与 A 小调音符完全相同，只差重心）
      · iTunes 的 30 秒预览通常取的是**副歌**，不代表整首歌的调性走向
    研究上 valence 的相关性本来也只有 r≈0.41。

    **产出一个看起来像模像样、实际是噪声的数字，比没有这个数字更糟** ——
    它会一路流进报告，而验证器只能证明「这个数字来自实测行」，
    证明不了「这个数字是对的」。

    所以：能量（arousal）用实测的，它是可靠的；
    效价改由流派映射提供，走 inference 那一档，报告里明确标出来源。
    mode_major 仍然保留 —— 它是诚实的原始测量，只是别过度解读。
    """

    tempo_bpm: float | None
    rms: float
    spectral_centroid: float
    spectral_rolloff: float
    zero_crossing_rate: float
    mode_major: bool | None
    mode_confidence: float

    # 只有能量。合成公式与权重见 AROUSAL_WEIGHTS
    arousal: float

    duration_s: float
    analyzer_version: str

    def as_row(self) -> dict:
        return asdict(self)


def extract(y: np.ndarray, sr: int = SAMPLE_RATE) -> AudioFeature:
    """从波形算全部特征。y 是单声道 float32。"""

    if y.ndim > 1:
        y = librosa.to_mono(y)

    duration_s = len(y) / sr

    # ---- 可直接测量的量 ----
    rms = float(np.sqrt(np.mean(y ** 2)))
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    rolloff = float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr)))
    zcr = float(np.mean(librosa.feature.zero_crossing_rate(y)))

    tempo_raw = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr)[0])[0])
    tempo = fold_tempo(tempo_raw)

    mode_major, mode_confidence = estimate_mode(y, sr)

    # ---- arousal：三个实测有效的量加权 ----
    arousal = sum(
        weight * normalize(
            {"rms": rms, "spectral_centroid": centroid, "zero_crossing_rate": zcr}[name],
            *RANGES[name],
        )
        for name, weight in AROUSAL_WEIGHTS.items()
    )

    return AudioFeature(
        tempo_bpm=round(tempo, 1) if tempo else None,
        rms=round(rms, 5),
        spectral_centroid=round(centroid, 1),
        spectral_rolloff=round(rolloff, 1),
        zero_crossing_rate=round(zcr, 5),
        mode_major=mode_major,
        mode_confidence=round(mode_confidence, 3),
        arousal=round(clamp01(arousal), 4),
        duration_s=round(duration_s, 1),
        analyzer_version=ANALYZER_VERSION,
    )


def describe(feature: AudioFeature) -> str:
    """给人看的一行说明。

    报告里的证据链要用它 ——「低能量」必须能落到具体数字上，不能只是一句话。
    验证器会拿这段文字去核 claim 里提到的量。

    【调性只有判得比较准时才写出来】判不准还写「小调」是在给报告递刀：
    白噪声都能被这个算法判成小调（冒烟测试里就是这样）。
    """
    parts = [f"能量 {feature.arousal:.2f}"]
    if feature.tempo_bpm:
        parts.append(f"{feature.tempo_bpm:.0f} BPM")
    parts.append(f"亮度 {feature.spectral_centroid:.0f} Hz")

    if feature.mode_major is not None and feature.mode_confidence >= 0.6:
        parts.append("大调" if feature.mode_major else "小调")

    return ", ".join(parts)
