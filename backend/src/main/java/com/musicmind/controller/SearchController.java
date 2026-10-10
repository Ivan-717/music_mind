package com.musicmind.controller;

import com.musicmind.security.CurrentUser;
import com.musicmind.service.SearchService;
import com.musicmind.vo.SearchVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/search")
@RequiredArgsConstructor
public class SearchController {

    private final SearchService searchService;

    @GetMapping
    public SearchVO search(@RequestParam("q") String q,
                           @RequestParam(value = "limit", required = false) Integer limit) {
        // userId 用于第二来源：搜「我的歌单里还没入库的」（越权天然隔离——只搜自己的）
        return searchService.search(q, limit, CurrentUser.id());
    }
}
