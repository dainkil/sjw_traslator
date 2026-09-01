package dev.sjw.common.llm;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** 레지스트리·활성 Translator 조립. BYOK(M2.5-S6)에서 요청 단위 생성으로 확장된다 (ADR-020). */
@Configuration
@EnableConfigurationProperties(LlmProperties.class)
public class LlmConfig {

    @Bean
    public ModelRegistry modelRegistry(LlmProperties props) {
        return new ModelRegistry(props);
    }

    @Bean
    public Translator translator(ChatClient.Builder builder, ModelRegistry registry) {
        return new GoogleGenAiTranslator(builder, registry.active().id());
    }
}
