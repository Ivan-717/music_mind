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
}
