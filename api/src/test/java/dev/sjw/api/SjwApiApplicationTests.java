package dev.sjw.api;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

// CI에서 실제 키 없이도 컨텍스트 로드가 가능하도록 더미 키 주입 (LLM 호출은 하지 않음)
@SpringBootTest(properties = "spring.ai.google.genai.api-key=dummy-for-context-load")
class SjwApiApplicationTests {

    @Test
    void contextLoads() {
    }
}
