package com.musicmind.controller;

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
        return searchService.search(q, limit);
    }
}
