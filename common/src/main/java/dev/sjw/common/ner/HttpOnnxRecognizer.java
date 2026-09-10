package dev.sjw.common.ner;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * ONNX NER 서버(:8100) HTTP 어댑터 — 운영 기본. 서버 내 추론 p50 8.3ms, HTTP 왕복 ~20ms (실측).
 * 모든 실패는 {@link NerUnavailableException}으로 드러낸다 — 빈 결과로 위장하지 않는다.
 */
public class HttpOnnxRecognizer implements EntityRecognizer {

    private static final Logger log = LoggerFactory.getLogger(HttpOnnxRecognizer.class);

    private final RestClient client;

    /** /healthz의 model_version — 한 번 받으면 고정한다 (모델 파일 교체 = 재기동이 이 프로젝트의 규약). */
    private volatile String modelVersion;

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

    /**
     * 서버의 모델 파생 버전. 아직 못 받았으면 이번 호출에서 한 번 시도하고, 실패하면 비운다 —
     * 그 경우 캐시가 조회·적재를 건너뛰므로 잘못된 키가 만들어지지 않는다.
     *
     * <p>한 번 받아둔 뒤 NER 서버가 죽어도 값은 유지된다. 지식 계층 장애 중에도 이미 캐시된
     * 문장은 계속 서빙된다는 뜻이다.
     */
    @Override
    public Optional<String> version() {
        String cached = modelVersion;
        if (cached != null) {
            return Optional.of(cached);
        }
        try {
            HealthResponse res = client.get().uri("/healthz").retrieve().body(HealthResponse.class);
            if (res != null && res.model_version() != null && !res.model_version().isBlank()) {
                modelVersion = res.model_version();
                log.info("NER 모델 버전: {}", modelVersion);
                return Optional.of(modelVersion);
            }
            log.warn("NER /healthz에 model_version이 없다 — 캐시를 건너뛴다");
        } catch (RuntimeException e) {
            log.warn("NER 모델 버전 조회 실패 — 캐시를 건너뛴다: {}", e.getMessage());
        }
        return Optional.empty();
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

    record HealthResponse(String status, String model_dir, String model_version) {}
}
