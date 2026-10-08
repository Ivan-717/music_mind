# 评估口径 v2 设计 —— 修三个失真点，加一个"认人"测试

> 起因：2026-10-08 重跑，content 在 random_item k=20 上 18.65% → 1.87%。
> 三层对照证明**不是代码回归**（git HEAD 旧代码逐位一致），是库长大后
> **旧口径的失真被揭穿**（详见 `eval-results.md` 同日那节）。
> 现状：这个口径连 content 和 random 都分不开了 —— 修。

---

## 一、三个失真点（各自独立，逐条修）

### ① random 的白拿命中 → 加 **lift 指标**

random 推 20 首，光靠"藏歌占全库的比例"（vdev 的歌占全库 ~10%）就能命中 ~2 首。
所以不能只看 recall 绝对值，要报**相对随机的提升**：

```
lift@k = (recall − recall_random) / (上界 − recall_random)
```

- 0 = 和瞎猜一样；1 = 吃满上界
- 上界那列不变（min(可检索, k) / 藏歌总数）
- **同一折的 recall_random 现算**（同 seed 的 random 基线），分母不用历史数字

### ② ~~artist_cold 拆 same / cold 两组~~ —— 设计稿的错，实现前砍掉了

**原设计**：拆 `recall_same`（同艺人延伸）和 `recall_cold`（排除藏歌艺人的候选）。

**为什么砍**（实现时想清楚的）：
- `artist_cold` 藏的是「整个艺人的全部曲目」——**藏歌全是该艺人**。候选里排除该艺人后，
  推的歌**永远不可能命中藏歌** → `recall_cold ≡ 0`，是个恒零指标。
- 它本来想测的「泛化到新艺人的能力」**离线没有 ground truth** ——
  「用户会不会喜欢这个新艺人」没有标签可算（play_history 已放弃）。
- **这个需求改由 §二的 discrimination 测试承担**：「认人」能被测、能被证伪；
  「泛化质量」测不了就不假装能测。

保留 `recall`（原口径）+ `lift`（§①）+ `novelty`（§③）三个，够了。

### ③ "命中已有的歌"和"推荐质量"是两回事 → 加 **novelty@k**

推的 k 首里「不在用户曲库」的比例。产品目标是推没听过的歌——
**recall 高但 novelty 低 = 在重复用户已有的**（旧口径的泄露红利就是这个形状）。

三个数一起看：`lift_cold`（泛化）× `recall_same`（延伸）× `novelty`（基本盘）。
单独看任何一个都会被另一种策略骗。

---

## 二、新增：用户区分度测试（`discrimination`）

**这是现有框架完全测不到的**：系统有没有真的在"认人"？

```
用 A 的曲库建画像 → 推 k 首
  recall_A = 这 k 首对【A 的留出集】的命中率
  recall_B = 这 k 首对【B 的留出集】的命中率   ← 注意是 B 的留出集
区分度 = recall_A − recall_B     （同一个 k、同一个折法）
```

- **应当显著为正**：给 A 推的东西应该更像 A 的、而不是 B 的
- 如果 ≈ 0：系统推的是"全库热门"，和用户无关 —— 这是个一测就死的信号
- 反过来再测一次（用 B 建画像），**双向**都为正才通过

**实现时发现的两个现实**（都写进了 `discrimination.py` 的输出提醒）：

1. **A/B 要先查重合率**：原本想用 vdev ↔ lizibin，一查**重合 89%——是同一个人的两个号**。
   换了 vdev ↔ 热歌榜测试号（重合 11%）。重合率 > 60% 时输出会自己标注"信号不可用"。
2. **库太小的一方测不出信号**：热歌榜号只有 61 首对齐 → 留出每折 12 首，
   命中 0 和 1 的差别是一首歌的抽样噪声。加 `MIN_HIDDEN = 30` 门槛，
   基数不够直接输出「不可判」——**不许把噪声显示成 ✗**。

**怎么让它变成硬门**：等有第二个真实用户（几百首、和 vdev 品味不同）就能真跑。
在那之前，它是一次跑完秒级、随时可复跑的哨兵。

---

## 三、实现落点（都在 `musicmind_agent/evals/`）

```
metrics.py     + lift(recall, recall_random, ceiling)
               + novelty(推荐 ids, 用户曲库 ids)
splits.py      + Fold 增加 artist_filter 维度（藏歌的艺人集合，评估循环里要用）
run_eval.py    + 每折先跑一次 random 拿 recall_random（同 seed）
               + content 跑两次：全候选（原样）和排除藏歌艺人（cold 版）
               + --systems discrimination --user-a 34 --user-b 131
results.csv    新列：lift_cold@k / recall_same@k / novelty@k / recall_random@k
```

**LLM 部分（agent_full / llm_only）等口径修好再跑** —— 否则新数字同样不可解释。

---

## 四、验收（就用今天的数据跑，不改任何推荐代码）

1. `discrimination` 双向为正（vdev ↔ lizibin）——**这是新的第一道门**
2. `lift_cold` 上：content 显著 > random ≈ genre_prior（期望 > 0.15；
   修口径后的数字会低得诚实，别再拿 83% 那种数当成绩）
3. `novelty@k` 上：content > 0.9（推荐的基本盘是不重复用户）
4. 旧的 recall 列**照常保留**（历史可比），新列并行加，不删旧口径
5. 全部离线秒级；不得调 LLM

## 五、明确不做

- 不引入真实播放/点击数据（`play_history` 已放弃，没有就是没有）
- 不做离线代理标签的机器学习那一套（样本量撑不起，原则 2）
- 不推翻 artist_cold / random_item 两个切分本身 —— 它们是标准做法，
  错的是指标的口径，不是折法
