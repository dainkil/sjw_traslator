package dev.sjw.common.llm;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.prompt.ChatOptions;
import reactor.core.publisher.Flux;

/**
 * Google Generative Language API 어댑터. 모델은 호출마다 옵션으로 지정하므로
 * 하나의 ChatClient가 레지스트리의 전 모델(gemini/gemma 계열)을 커버한다.
 * temperature 등 나머지 옵션은 yml 기본값(spring.ai.google.genai.chat.options)을 따른다.
 */
public class GoogleGenAiTranslator implements Translator {

    private final ChatClient chatClient;
    private final String modelId;

    public GoogleGenAiTranslator(ChatClient.Builder builder, String modelId) {
        this.chatClient = builder.build();
        this.modelId = modelId;
    }

    @Override
    public String modelId() {
        return modelId;
    }

    @Override
    public LlmReply call(String prompt) {
        var resp = chatClient.prompt().options(ChatOptions.builder().model(modelId))
                .user(prompt).call().chatResponse();
        if (resp == null) {
            return new LlmReply(null, null, null);
        }
        var usage = resp.getMetadata().getUsage();
        return new LlmReply(
                resp.getResult().getOutput().getText(),
                usage == null ? null : usage.getPromptTokens(),
                usage == null ? null : usage.getCompletionTokens());
    }

    @Override
    public Flux<String> stream(String prompt) {
        return chatClient.prompt().options(ChatOptions.builder().model(modelId))
                .user(prompt).stream().content();
    }
}
