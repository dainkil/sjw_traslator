package dev.sjw.common.ner;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.List;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * ONNX NER 서버(:8100) HTTP 어댑터 — 운영 기본. 서버 내 추론 p50 8.3ms, HTTP 왕복 ~20ms (실측).
 * 모든 실패는 {@link NerUnavailableException}으로 드러낸다 — 빈 결과로 위장하지 않는다.
 */
public class HttpOnnxRecognizer implements EntityRecognizer {

    private final RestClient client;

    public HttpOnnxRecognizer(String baseUrl) {
        var factory = new JdkClientHttpRequestFactory(
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build());
        factory.setReadTimeout(Duration.ofSeconds(10)); // 실측 p95 62ms — 10s면 장애다
        this.client = RestClient.builder().baseUrl(baseUrl).requestFactory(factory).build();
    }

    @Override
    public String id() {
        return "onnx-http";
    }

    @Override
    public List<NerEntity> extract(String text) {
        NerResponse res;
        try {
            res = client.post()
                    .uri("/v1/ner")
                    .body(new NerRequest(text, 0.5))
                    .retrieve()
                    .body(NerResponse.class);
        } catch (RuntimeException e) {
            throw new NerUnavailableException("NER 서버 호출 실패: " + e.getMessage(), e);
        }
        if (res == null || res.entities() == null) {
            throw new NerUnavailableException("NER 서버가 200을 반환했으나 본문이 비정상");
        }
        return res.entities();
    }

    record NerRequest(String text, double min_score) {}

    record NerResponse(List<NerEntity> entities, double latency_ms) {}
}
