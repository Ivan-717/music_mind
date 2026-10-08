package com.musicmind.util;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertTrue;

/** 繁简变体扩展。这个错了不会报错，只会「什么都搜不到」。 */
class KeywordVariantsTest {

    @Test
    void expandsBothDirections() {
        List<String> v = KeywordVariants.of("林俊杰");
        System.out.println("### 林俊杰 -> " + v);
        assertTrue(v.contains("林俊杰"), "原始词必须在");
        assertTrue(v.contains("林俊傑"), "繁体形式没转出来，MusicBrainz 的结果会被全部滤掉：" + v);
    }

    @Test
    void knownCaseStillWorks() {
        List<String> v = KeywordVariants.of("周杰伦");
        System.out.println("### 周杰伦 -> " + v);
        assertTrue(v.contains("周杰倫"), v.toString());
    }

    @Test
    void stripsParenthesizedSuffix() {
        // 库里的「流行歌曲 (Popular Songs)」要靠这个变体才能和歌单的「流行歌曲」
        // 等值比上（2026-10-07：一直 UNRESOLVED，推荐还把它推回给用户）
        List<String> v = KeywordVariants.of("晴天 (Live)");
        System.out.println("### 晴天 (Live) -> " + v);
        assertTrue(v.contains("晴天"), "剥掉括号后缀的形式必须在：" + v);

        List<String> v2 = KeywordVariants.of("晴天（Live）");
        assertTrue(v2.contains("晴天"), "全角括号也要剥：" + v2);

        // 本来就是干净的词，不受影响
        assertTrue(KeywordVariants.of("流行歌曲").contains("流行歌曲"));
    }
}
