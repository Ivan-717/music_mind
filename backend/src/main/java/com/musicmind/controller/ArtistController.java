package com.musicmind.controller;

import com.musicmind.service.ArtistService;
import com.musicmind.vo.ArtistDetailVO;
import com.musicmind.vo.MbArtistVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/artists")
@RequiredArgsConstructor
public class ArtistController {

    private final ArtistService artistService;

    /**
     * 去 MusicBrainz 查歌手——本地搜不到时才用。
     *
     * 路径是字面量 /lookup，比 /{id} 更具体，Spring 会优先匹配它，
     * 不会被当成 id=lookup 去转 Long。
     */
    @GetMapping("/lookup")
    public List<MbArtistVO> lookup(@RequestParam("q") String q,
                                   @RequestParam(value = "limit", required = false) Integer limit) {
        return artistService.lookup(q, limit);
    }

    @GetMapping("/{id}")
    public ArtistDetailVO detail(@PathVariable Long id) {
        return artistService.detail(id);
    }
}
