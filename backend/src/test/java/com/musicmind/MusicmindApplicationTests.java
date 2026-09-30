package com.musicmind;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(properties = "ingestion.worker-enabled=false")
class MusicmindApplicationTests {

    // 关掉入库 worker：它是 SmartLifecycle，上下文一起来就会开始消费队列。
    // 不关的话，本地队列里有任务时跑 mvn test = 真的抓取 + 真的写库

    @Test
    void contextLoads() {
    }

}
