package dev.sjw.api.ner;

import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class NerClient {

    private final RestClient client;

    public NerClient(@Value("${sjw.ner.url}") String baseUrl) {
        this.client = RestClient.builder().baseUrl(baseUrl).build();
    }

    public List<NerEntity> extract(String text) {
        NerResponse res = client.post()
                .uri("/v1/ner")
                .body(new NerRequest(text, 0.5))
                .retrieve()
                .body(NerResponse.class);
        return res == null ? List.of() : res.entities();
    }

    record NerRequest(String text, double min_score) {}

    record NerResponse(List<NerEntity> entities, double latency_ms) {}
}
