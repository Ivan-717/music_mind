package com.musicmind.util;

import com.github.houbb.opencc4j.util.ZhConverterUtil;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;

/**
 * 查询词的繁简变体扩展。
 *
 * 背景：数据层忠实保存 MusicBrainz 的繁体原样（见繁简政策），
 * 所以用户搜简体的「周杰伦」时，LIKE 匹配不到库里的「周杰倫」。
 * 解法：不动数据一行，只在查询时把关键词扩成变体集合再 OR。
 *
 * 【这里故意不加假名跳过规则】——前端展示层是加的，两者不同：
 *   展示层：转换结果直接显示，误伤会显示错误内容 → 必须跳过含假名的串
 *   查询层：转换结果只用于扩成 OR 条件，原始词永远在集合里 →
 *           即使 toSimple 把日文汉字误改，原始词照样命中，多出的变体无害
 * 改这里之前先想清楚上面这段，别把展示层的规则顺手搬过来。
 */
public final class KeywordVariants {

    private KeywordVariants() {
    }

    /**
     * 返回去重后的变体列表，【原始词固定排在第一位】。
     * 关键词为空时返回空列表。
     */
    public static List<String> of(String keyword) {
        if (keyword == null) {
            return List.of();
        }
        String trimmed = keyword.trim();
        if (trimmed.isEmpty()) {
            return List.of();
        }

        // LinkedHashSet：去重 + 保持插入顺序（顺序稳定才好调试和断言）
        LinkedHashSet<String> set = new LinkedHashSet<>();
        set.add(trimmed);                                  // 原始词，必须第一个
        set.add(ZhConverterUtil.toSimple(trimmed));        // 简体形式
        set.add(ZhConverterUtil.toTraditional(trimmed));   // 繁体形式
        set.removeIf(s -> s == null || s.isEmpty());

        // 再去掉空格。
        //
        // 网易云写「G.E.M.邓紫棋」，MusicBrainz 写「G.E.M. 鄧紫棋」，就差一个空格——
        // 和繁简一样，是同一个名字的两种写法，不是需要语义理解的模糊匹配。
        // 归一化【两边都要做】：这里去变体的空格，SQL 里对列套 REPLACE。
        // 只做一边没用——库里那边还带着空格。
        List<String> result = new ArrayList<>();
        for (String variant : set) {
            String noSpace = variant.replace(" ", "");
            if (!noSpace.isEmpty()) {
                result.add(noSpace);
            }
        }
        return result;
    }

    /**
     * 取第 i 个变体；越界时【返回第一个变体】而不是 null。
     *
     * 为什么不是 null：SQL 里下面这种写法会静默算错——
     *     NOT (name LIKE '%'||v1||'%' OR name LIKE '%'||v2||'%' OR name LIKE '%'||v3||'%')
     * 当 v3 是 NULL 时，三个都是假的行得到 `NOT (FALSE OR FALSE OR NULL)` = `NOT NULL` = NULL，
     * 在 WHERE 里按假处理，整行被丢掉。正的 OR 匹配不受影响，但取反就废了。
     *
     * 用第一个变体填满，三个参数永远非空，条件只是冗余而不会出错。
     */
    public static String at(List<String> variants, int i) {
        if (variants.isEmpty()) {
            return null;
        }
        return i < variants.size() ? variants.get(i) : variants.get(0);
    }
}
