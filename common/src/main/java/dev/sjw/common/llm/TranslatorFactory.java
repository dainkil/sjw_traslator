package dev.sjw.common.llm;

import org.springframework.ai.chat.client.ChatClient;

/**
 * 레지스트리 모델 id → Translator. 품질 게이트의 티어 승격(§5.4)이 활성 모델 밖의
 * 모델을 1회성으로 쓰는 통로다. id는 레지스트리 검증을 거친다 — 미등록 모델로는 못 만든다.
 */
public class TranslatorFactory {

    private final ChatClient.Builder builder;
    private final ModelRegistry registry;

    public TranslatorFactory(ChatClient.Builder builder, ModelRegistry registry) {
        this.builder = builder;
        this.registry = registry;
    }

    public Translator forModel(String modelId) {
        return new GoogleGenAiTranslator(builder, registry.require(modelId).id());
    }
}
