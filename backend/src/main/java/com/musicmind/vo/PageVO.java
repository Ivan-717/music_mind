package com.musicmind.vo;

import lombok.Data;

import java.util.List;

@Data
public class PageVO<T> {
    private long total;
    private int page;
    private int size;
    private List<T> items;
}