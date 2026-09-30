package com.musicmind.util;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * ArtistText 的测试。
 *
 * 【为什么这一条值得有测试】切分拿的是「外部歌单给的拼接串」，切错了不会报错，
 * 只会静默地永远匹配不上——歌永久停在「未收录」，点入库也没用（去搜的是别人）。
 * 这类 bug 没有异常、没有日志，只能靠断言挡住。
 *
 * 不起 Spring 上下文：纯函数，跑一次几毫秒。
 */
class ArtistTextTest {

    @Test
    void singleArtistReturnedAsIs() {
        assertEquals("周杰伦", ArtistText.primary("周杰伦"));
        assertEquals("G.E.M.邓紫棋", ArtistText.primary("G.E.M.邓紫棋"));
    }

    @Test
    void multipleArtistsTakeFirst() {
        assertEquals("周杰伦", ArtistText.primary("周杰伦 / 温岚"));
        assertEquals("周杰伦", ArtistText.primary("周杰伦 / 温岚 / 费玉清"));
    }

    /**
     * 【回归】艺人名自带的斜杠不是分隔符。
     *
     * 拼接用的是 " / "（前后带空格），早期实现按裸 '/' 切，
     * 于是 AC/DC 被腰斩成 AC —— 拿 AC 去比 artist.name 永远对不上，
     * 去 MusicBrainz 搜也搜的是别人，这首歌就永远进不了库。
     */
    @Test
    void slashInsideNameIsNotASeparator() {
        assertEquals("AC/DC", ArtistText.primary("AC/DC"));
        assertEquals("AC/DC", ArtistText.primary("AC/DC / Axl Rose"));
        assertEquals("K/DA", ArtistText.primary("K/DA"));
    }

    /**
     * 只剩分隔符的脏数据不能返回一个叫「/」的艺人。
     *
     * trim 会先吃掉两侧空格，于是 " / " 变成 "/"，这时已经找不到 " / " 分隔符了，
     * 不挡的话会返回 "/" —— 拿它去搜 MusicBrainz、比 artist.name 都是纯浪费。
     */
    @Test
    void separatorOnlyIsNull() {
        assertNull(ArtistText.primary(" / "));
        assertNull(ArtistText.primary("/"));
    }

    /**
     * 首个歌手是空的（脏数据）时退到下一个非空的名字。
     *
     * 比返回 null 有用：至少还能拿去匹配和搜 MusicBrainz。
     * 注意这和 ParsedTrack.primaryArtist()（直接取 artists[0]）行为不同，
     * 那个是导入时的路径，拿不到就退回未对齐；这里是入库路径，能救一个是一个。
     */
    @Test
    void emptyLeadSegmentFallsThroughToNextName() {
        assertEquals("温岚", ArtistText.primary(" / 温岚"));
    }

    @Test
    void nullAndBlankAreNull() {
        assertNull(ArtistText.primary(null));
        assertNull(ArtistText.primary(""));
        assertNull(ArtistText.primary("   "));
    }

    @Test
    void surroundingSpacesTrimmed() {
        assertEquals("周杰伦", ArtistText.primary("  周杰伦  /  温岚"));
        assertEquals("周杰伦", ArtistText.primary("周杰伦 "));
    }
}
