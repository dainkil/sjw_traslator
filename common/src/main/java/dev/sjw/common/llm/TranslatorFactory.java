package dev.sjw.common.llm;

import com.google.genai.Client;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.google.genai.GoogleGenAiChatModel;
import org.springframework.ai.google.genai.GoogleGenAiChatOptions;

/**
 * 레지스트리 모델 id → Translator. 품질 게이트의 티어 승격(§5.4)과 BYOK(D10)가
 * 활성 싱글턴 밖의 클라이언트를 만드는 통로다. id는 레지스트리 검증을 거친다.
 */
public class TranslatorFactory {

    private final ChatClient.Builder builder;
    private final ModelRegistry registry;

    public TranslatorFactory(ChatClient.Builder builder, ModelRegistry registry) {
        this.builder = builder;
        this.registry = registry;
    }

    /** 운영자 키(자동 구성 ChatClient)로 — 티어 승격 등 내부 용도. */
    public Translator forModel(String modelId) {
        return new GoogleGenAiTranslator(builder, registry.require(modelId).id());
    }

    /**
     * BYOK: 요청자가 가져온 LLM 키로 요청 단위 클라이언트를 만든다 (ADR-020).
     * 키는 이 스택 프레임 밖으로 나가지 않는다 — 저장·로깅 금지. 반환된 Translator를
     * 요청 처리 후 버리면 키도 함께 사라진다.
     */
    public Translator forModelWithKey(String modelId, String llmApiKey) {
        ModelSpec spec = registry.require(modelId);
        var chatModel = GoogleGenAiChatModel.builder()
                .genAiClient(Client.builder().apiKey(llmApiKey).build())
                .options(GoogleGenAiChatOptions.builder().model(spec.id()).temperature(0.2).build())
                .build();
        return new GoogleGenAiTranslator(ChatClient.builder(chatModel), spec.id());
    }
}
