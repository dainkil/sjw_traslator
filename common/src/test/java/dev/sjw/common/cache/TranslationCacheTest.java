package dev.sjw.common.cache;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import dev.sjw.common.kb.KbPerson;
import dev.sjw.common.kb.KnowledgeSource;
import dev.sjw.common.kb.LinkResult;
import dev.sjw.common.ner.EntityRecognizer;
import dev.sjw.common.ner.NerEntity;
import dev.sjw.common.quality.QualityGrade;
import dev.sjw.common.translate.PromptAssembler;
import dev.sjw.common.translate.TranslationDtos.EntityDto;
import dev.sjw.common.translate.TranslationDtos.Meta;
import dev.sjw.common.translate.TranslationDtos.TranslationResponse;
import dev.sjw.common.translate.TranslationDtos.UncertainSpan;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * L1 캐시 실동작 검증 (M3-S2).
 *
 * <p>실제 Redis에 붙는다 — 검증 대상의 절반이 "버전이 갈리면 키가 달라진다"는 저장소 동작이라
 * 인메모리 대역으로는 의미가 없다. Redis가 없으면 {@code assumeTrue}로 건너뛴다:
 * {@code docker compose -f deploy/docker-compose.yml up -d}
 *
 * <p>테스트마다 kb 버전을 난수로 잡아 키 공간을 격리한다.
 */
class TranslationCacheTest {

    private static final String SOURCE = "以李馨長爲承旨";

    private static LettuceConnectionFactory factory;
    private static StringRedisTemplate redis;

    private final List<String> usedKbVersions = new ArrayList<>();

    @BeforeAll
    static void connect() {
        factory = new LettuceConnectionFactory(new RedisStandaloneConfiguration("localhost", 6379));
        factory.afterPropertiesSet();
        factory.start();
        redis = new StringRedisTemplate(factory);
        redis.afterPropertiesSet();

        boolean alive;
        RedisConnection conn = null;
        try {
            conn = factory.getConnection();
            alive = "PONG".equalsIgnoreCase(conn.ping());
        } catch (Exception e) {
            alive = false;
        } finally {
            if (conn != null) {
                try {
                    conn.close();
                } catch (Exception ignored) {
                    // 검증 대상이 아님
                }
            }
        }
        assumeTrue(alive, "로컬 Redis(:6379)가 없어 건너뜀 — docker compose -f deploy/docker-compose.yml up -d");
    }

    @AfterAll
    static void disconnect() {
        if (factory != null) {
            factory.destroy();
        }
    }

    @AfterEach
    void cleanup() {
        for (String kbVersion : usedKbVersions) {
            Set<String> keys = redis.keys("cache:l1:" + kbVersion + ":*");
            if (keys != null && !keys.isEmpty()) {
                redis.delete(keys);
            }
        }
        usedKbVersions.clear();
    }

    @Test
    void 적재한_결과가_번역문_엔티티_등급_생산모델까지_보존된다() {
        String kbVersion = kbVersion();
        TranslationCache cache = cache(kbVersion, "prompt-1", "onnx-1", "1", true, new SimpleMeterRegistry());

        cache.storeL1(SOURCE, response("이형장을 승지로 삼았다"), QualityGrade.VERIFIED);
        CachedTranslation hit = cache.lookupL1(SOURCE).orElseThrow();

        assertEquals("이형장을 승지로 삼았다", hit.translatedText());
        assertEquals("VERIFIED", hit.qualityGrade());
        assertEquals("gemini-3.1-flash-lite", hit.producedModel());
        assertEquals(1, hit.entities().size());
        assertEquals("이형장", hit.entities().get(0).resolvedName());
        assertEquals(1, hit.uncertainSpans().size());
    }

    @Test
    void REJECTED는_적재되지_않는다() {
        String kbVersion = kbVersion();
        TranslationCache cache = cache(kbVersion, "prompt-1", "onnx-1", "1", true, new SimpleMeterRegistry());

        cache.storeL1(SOURCE, response("확정 인명이 빠진 번역"), QualityGrade.REJECTED);

        assertTrue(cache.lookupL1(SOURCE).isEmpty(), "오역이 캐시에 박히면 계속 서빙된다");
    }

    @Test
    void 인물사전_버전이_바뀌면_미스가_된다() {
        String kbVersion = kbVersion();
        cache(kbVersion, "prompt-1", "onnx-1", "1", true, new SimpleMeterRegistry())
                .storeL1(SOURCE, response("옛 KB 결과"), QualityGrade.VERIFIED);

        // 오링크 교정 후 옛 결과가 계속 나오는 것이 ADR-009가 막으려는 실패 모드다
        TranslationCache afterKbUpdate =
                cache(kbVersion(), "prompt-1", "onnx-1", "1", true, new SimpleMeterRegistry());
        assertTrue(afterKbUpdate.lookupL1(SOURCE).isEmpty());
    }

    @Test
    void 프롬프트_버전이_바뀌면_미스가_된다() {
        String kbVersion = kbVersion();
        cache(kbVersion, "prompt-1", "onnx-1", "1", true, new SimpleMeterRegistry())
                .storeL1(SOURCE, response("옛 프롬프트 결과"), QualityGrade.VERIFIED);

        assertTrue(cache(kbVersion, "prompt-2", "onnx-1", "1", true, new SimpleMeterRegistry())
                .lookupL1(SOURCE).isEmpty());
    }

    @Test
    void NER_모델_버전이_바뀌면_미스가_된다() {
        String kbVersion = kbVersion();
        cache(kbVersion, "prompt-1", "onnx-1", "1", true, new SimpleMeterRegistry())
                .storeL1(SOURCE, response("옛 NER로 만든 결과"), QualityGrade.VERIFIED);

        // 재학습본으로 갈아끼웠는데 캐시가 옛 결과를 내주면 개선분이 캐시에 막혀 사라진다
        assertTrue(cache(kbVersion, "prompt-1", "onnx-2", "1", true, new SimpleMeterRegistry())
                .lookupL1(SOURCE).isEmpty());
    }

    @Test
    void epoch를_올리면_미스가_된다() {
        String kbVersion = kbVersion();
        cache(kbVersion, "prompt-1", "onnx-1", "1", true, new SimpleMeterRegistry())
                .storeL1(SOURCE, response("옛 모델로 만든 결과"), QualityGrade.VERIFIED);

        // 번역 LLM 교체용 수동 손잡이 — 키에 모델이 없는 대신 이 값이 전면 재구축을 만든다
        assertTrue(cache(kbVersion, "prompt-1", "onnx-1", "2", true, new SimpleMeterRegistry())
                .lookupL1(SOURCE).isEmpty());
    }

    @Test
    void NER_버전을_못_받으면_조회도_적재도_하지_않는다() {
        String kbVersion = kbVersion();
        MeterRegistry meters = new SimpleMeterRegistry();
        TranslationCache offline = cache(kbVersion, "prompt-1", null, "1", true, meters);

        offline.storeL1(SOURCE, response("버전 없는 상태의 결과"), QualityGrade.VERIFIED);
        assertTrue(offline.lookupL1(SOURCE).isEmpty());

        // 버전을 확보한 뒤에도 남아 있으면 안 된다 — 애초에 적재되지 않았어야 한다
        assertTrue(cache(kbVersion, "prompt-1", "onnx-1", "1", true, new SimpleMeterRegistry())
                .lookupL1(SOURCE).isEmpty());
    }

    @Test
    void 비활성이면_적재_조회_모두_무동작이고_미스로도_세지_않는다() {
        String kbVersion = kbVersion();
        MeterRegistry meters = new SimpleMeterRegistry();
        TranslationCache off = cache(kbVersion, "prompt-1", "onnx-1", "1", false, meters);

        off.storeL1(SOURCE, response("꺼진 상태의 결과"), QualityGrade.VERIFIED);
        assertTrue(off.lookupL1(SOURCE).isEmpty());

        // 기능을 꺼둔 것과 캐시가 못 맞춘 것은 다르다 — 분모를 오염시키면 on/off 비교가 무의미해진다
        assertNull(meters.find("translation.cache.miss").counter());
        assertTrue(cache(kbVersion, "prompt-1", "onnx-1", "1", true, new SimpleMeterRegistry())
                .lookupL1(SOURCE).isEmpty(), "꺼진 상태에서는 적재도 없었어야 한다");
    }

    @Test
    void 히트와_미스가_각각_계측된다() {
        String kbVersion = kbVersion();
        MeterRegistry meters = new SimpleMeterRegistry();
        TranslationCache cache = cache(kbVersion, "prompt-1", "onnx-1", "1", true, meters);

        assertTrue(cache.lookupL1(SOURCE).isEmpty());
        cache.storeL1(SOURCE, response("이형장을 승지로 삼았다"), QualityGrade.VERIFIED);
        assertTrue(cache.lookupL1(SOURCE).isPresent());

        assertEquals(1.0, meters.get("translation.cache.miss").tag("level", "L1").counter().count());
        assertEquals(1.0, meters.get("translation.cache.hit").tag("level", "L1").counter().count());
    }

    @Test
    void 히트를_응답으로_되살리면_토큰은_비고_생산모델과_히트층위가_남는다() {
        String kbVersion = kbVersion();
        TranslationCache cache = cache(kbVersion, "prompt-1", "onnx-1", "1", true, new SimpleMeterRegistry());
        cache.storeL1(SOURCE, response("이형장을 승지로 삼았다"), QualityGrade.VERIFIED);

        TranslationResponse resp = cache.toResponse(cache.lookupL1(SOURCE).orElseThrow(), 3);

        assertEquals("L1_EXACT", resp.meta().cacheHit());
        assertEquals("gemini-3.1-flash-lite", resp.meta().model());
        assertNull(resp.meta().tokensIn(), "쓰지 않은 토큰을 계상하면 비용 SLI가 오염된다");
        assertNull(resp.meta().tokensOut());
        assertEquals(kbVersion, resp.meta().kbVersion());
        assertEquals(3L, resp.meta().latencyMs().get("total"));
    }

    // --- 조립 도구 -------------------------------------------------------

    private String kbVersion() {
        String v = "kbtest-" + UUID.randomUUID().toString().substring(0, 8);
        usedKbVersions.add(v);
        return v;
    }

    private TranslationCache cache(String kbVersion, String promptVersion, String nerVersion,
                                   String epoch, boolean enabled, MeterRegistry meters) {
        var versions = new PipelineVersions(kb(kbVersion), prompt(promptVersion), ner(nerVersion), epoch);
        return new TranslationCache(redis, versions, meters, enabled, 30);
    }

    private static TranslationResponse response(String translated) {
        return new TranslationResponse(
                translated,
                List.of(new EntityDto("李馨長", "PER", "P1", "이형장", 0.94, "EXACT", false)),
                List.of(new UncertainSpan("某", "KB_MISS")),
                new Meta("gemini-3.1-flash-lite", "kb", "prompt", 412, 158,
                        Map.of("llm", 900L), null));
    }

    private static KnowledgeSource kb(String version) {
        return new KnowledgeSource() {
            @Override
            public String version() {
                return version;
            }

            @Override
            public KbPerson person(String id) {
                return null;
            }

            @Override
            public LinkResult link(String mention, int currentYear, String contextText) {
                return null;
            }
        };
    }

    private static PromptAssembler prompt(String version) {
        return new PromptAssembler() {
            @Override
            public String version() {
                return version;
            }
        };
    }

    private static EntityRecognizer ner(String version) {
        return new EntityRecognizer() {
            @Override
            public String id() {
                return "stub";
            }

            @Override
            public Optional<String> version() {
                return Optional.ofNullable(version);
            }

            @Override
            public List<NerEntity> extract(String text) {
                return List.of();
            }
        };
    }
}
