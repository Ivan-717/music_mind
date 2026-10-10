/**
 * LLM 消耗估价（人民币，每百万 token）。
 *
 * 【为什么放前端不放库】价格会变，落库等于每次调价都要迁移历史数据；
 * 而 provider/model/tokens 三个原料已经全在报告里（agent_report 表 +
 * 报告详情 API 已透出）。分工照旧：Java 原样透传、前端渲染。
 *
 * 【四条硬规则（写这张表之前先读）】
 *   1. 键用 provider + model 正则前缀，**不写全等** —— model 来自 .env，
 *      带日期后缀的别名很常见（deepseek-chat-2026xx…）
 *   2. **认不出 (provider, model) 返回 null**，UI 只显示 token 不显示钱。
 *      宁可不显示，也不给一个错的数字
 *   3. 币种跟着条目走，**不做汇率换算**
 *   4. 口径：我们存的 token 数【分不出】缓存命中/未命中 →
 *      表里存**未命中价**（错峰优惠也不计），文案固定「≈」（估算）
 *
 * 【数值来源】填错比不填更糟 —— 加新条目必须带来源和日期：
 *   · deepseek-chat：2026-05 DeepSeek 官方文档，输入（缓存未命中）¥1 / 输出 ¥2。
 *     注：deepseek-chat 已进入弃用过渡期（实际按 deepseek-v4-flash 计费）；
 *     缓存命中的输入只要 ¥0.02，我们按未命中算 —— 是上界
 *   · qwen-plus：阿里云百炼内地价（2026），输入 ¥0.8 / 输出 ¥2（非思考档）。
 *     项目 .env 目前配的是 qwen-math-turbo（数学模型）—— 不在表里，走 null 降级
 */
export const RATES_UPDATED = '2026-10-09'

const RATES = [
  { provider: 'deepseek', match: /^deepseek-(chat|v4-flash)/, currency: 'CNY', in: 1, out: 2 },
  { provider: 'qwen', match: /^qwen-plus/, currency: 'CNY', in: 0.8, out: 2 }
]

/**
 * 估一次生成的费用。认不出 provider/model 返回 null（UI 只显示 token）。
 * @returns {{ amount: number, currency: string, text: string } | null}
 */
export function estimateCost(provider, model, tokensIn, tokensOut) {
  if (!provider || !model || (tokensIn == null && tokensOut == null)) return null
  const rate = RATES.find((r) => r.provider === provider && r.match.test(model))
  if (!rate) return null

  const amount =
    ((tokensIn || 0) / 1e6) * rate.in + ((tokensOut || 0) / 1e6) * rate.out
  const symbol = rate.currency === 'CNY' ? '¥' : '$'
  return {
    amount,
    currency: rate.currency,
    text: `${symbol}${amount.toFixed(3)}`
  }
}
