package com.musicmind.service.imports;

/**
 * 一个外部歌单平台的抓取实现。
 *
 * 【为什么要这层抽象】这些接口都不是官方开放的，没有文档保证、随时可能变。
 * 变化时只应该改对应的实现类，不该动 ImportService 和前端。
 *
 * 【失败必须吵】Provider 拿不到数据时要抛 ApiException，
 * 不能返回空列表——接口变了要让人立刻知道，
 * 而不是显示成「你的歌单是空的」。
 */
public interface PlaylistProvider {

    /** 平台标识，用于回给前端和写进日志 */
    String name();

    /** 这个链接是不是本平台能处理的 */
    boolean supports(String url);

    /** 抓取。失败抛 ApiException(502)，不要吞。 */
    ParsedPlaylist fetch(String url);
}
