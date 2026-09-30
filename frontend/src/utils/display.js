// 用 'opencc-js/t2cn' 而不是默认入口 'opencc-js'：
// 默认入口是 full.js，把简→繁、香港、日本等所有方向的词典都打进来（1.19 MB）。
// 我们只用 tw->cn 一个方向，t2cn 入口只带这一份词典，输出逐条一致。
import { Converter } from 'opencc-js/t2cn'

// 假名区段。注意排除了 U+30FB（・ 中点）——它是标点不是假名，
// 「我落淚・情緒零碎」这种中文标题会被它误判。
const KANA = /[\u3041-\u3096\u309D-\u309F\u30A1-\u30FA\u30FC-\u30FE\uFF66-\uFF9D]/

// tw(台湾正体) -> cn(大陆简体)
const t2s = Converter({ from: 'tw', to: 'cn' })

/**
 * 繁体转简体。含假名的字符串原样返回。
 *
 * 为什么要有假名判断：「僕のヒーローアカデミア」裸转会变成
 * 「仆のヒーローアカデミア」——僕 是日文的「我」，不是中文「仆」的繁体。
 * 机械转换不认识日文，会把日文汉字当繁体字改掉，那是在破坏作品原名。
 */
export function toSimplified(s) {
  if (typeof s !== 'string' || s === '') return s
  if (KANA.test(s)) return s
  return t2s(s)
}
