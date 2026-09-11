package dev.sjw.common.cache;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.sjw.common.kb.KbPerson;
import dev.sjw.common.kb.KnowledgeSource;
import dev.sjw.common.kb.LinkResult;
import dev.sjw.common.ner.EntityRecognizer;
import dev.sjw.common.ner.NerEntity;
import dev.sjw.common.quality.QualityGate;
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
 * L1 캐시 실동작 검증 (M3-S2) + L2 템플릿 슬롯 캐시 (M3-S3).
 *
 * <p>실제 Redis에 붙는다 — 검증 대상의 절반이 "버전이 갈리면 키가 달라진다"는 저장소 동작이라
 * 인메모리 대역으로는 의미가 없다. Redis가 없으면 {@code assumeTrue}로 건너뛴다:
 * {@code docker compose -f deploy/docker-compose.yml up -d}
 *
 * <p>테스트마다 kb 버전을 난수로 잡아 키 공간을 격리한다.
 */
class TranslationCacheTest {

    private static final String SOURCE = "以李馨長爲承旨";

    /**
     * L2 픽스처: <b>구조가 같고 인물만 다른</b> 두 문장. 둘 다 인조 연간 KB에서 단일 후보로
     * 확정되고 라이브 NER이 PER로 검출하는 실제 인물이다 (兪榥→유황 / 金瑬→김류).
     * 유황은 받침이 있고 김류는 없어서 재주입의 조사 보정이 드러난다.
     */
    private static final String SRC_A = "以兪榥爲承旨";
    private static final String SRC_B = "以金瑬爲承旨";
    private static final String TRANS_A = "유황을 승지로 삼았다.";

    private static final TemplateSlotter SLOTTER = new TemplateSlotter();

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
            for (String level : new String[] {"l1", "l2"}) {
                Set<String> keys = redis.keys("cache:" + level + ":" + kbVersion + ":*");
                if (keys != null && !keys.isEmpty()) {
                    redis.delete(keys);
                }
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

    // --- L2: 템플릿 슬롯 캐시 (M3-S3) -----------------------------------

    @Test
    void L2가_꺼져있어도_템플릿해시는_돌려주고_조회_적재는_하지_않는다() {
        String kbVersion = kbVersion();
        MeterRegistry meters = new SimpleMeterRegistry();
        TranslationCache off = cache(kbVersion, "prompt-1", "onnx-1", "1", false, false, meters);

        // 기본값이 off인데도 해시가 나와야 한다 — S4의 히트율 시뮬레이션은 "L2를 껐던 기간의
        // job들이 서로 틀을 공유했는가"를 job.template_hash로 사후 계산한다
        var lookup = off.lookupL2(SRC_A, per("兪榥", "유황")).orElseThrow();
        assertNull(lookup.translatedText(), "꺼진 상태에서 히트가 나오면 opt-in이 깨진 것이다");
        assertEquals(64, lookup.templateHash().length(), "SHA-256 hex");

        off.storeL2(SRC_A, per("兪榥", "유황"), translated(TRANS_A), QualityGrade.VERIFIED);
        assertTrue(l2Cache(kbVersion, new SimpleMeterRegistry())
                .lookupL2(SRC_A, per("兪榥", "유황")).orElseThrow().hit() == false,
                "꺼진 상태에서는 적재도 없었어야 한다");

        // 기능을 꺼둔 것은 미스가 아니다 (분모 오염 금지 — S2와 같은 규칙)
        assertNull(meters.find("translation.cache.miss").counter());
    }

    @Test
    void 구조가_같고_인물만_다른_문장이_히트하고_인명이_교체된다() {
        String kbVersion = kbVersion();
        TranslationCache cache = l2Cache(kbVersion, new SimpleMeterRegistry());

        cache.storeL2(SRC_A, per("兪榥", "유황"), translated(TRANS_A), QualityGrade.VERIFIED);
        var hit = cache.lookupL2(SRC_B, per("金瑬", "김류")).orElseThrow();

        assertTrue(hit.hit(), "以⟪PER1⟫爲承旨 — 같은 틀이므로 히트해야 한다");
        // 조사 보정: 유황(받침 O)의 '을'이 김류(받침 X)에서 '를'로 바뀐다
        assertEquals("김류를 승지로 삼았다.", hit.translatedText());
        assertEquals("gemini-3.1-flash-lite", hit.producedModel(),
                "틀을 만든 모델은 값에 보존된다 (키에는 없다)");
    }

    @Test
    void 같은_문장이면_원래_인명이_그대로_복원된다() {
        TranslationCache cache = l2Cache(kbVersion(), new SimpleMeterRegistry());
        cache.storeL2(SRC_A, per("兪榥", "유황"), translated(TRANS_A), QualityGrade.VERIFIED);

        assertEquals(TRANS_A,
                cache.lookupL2(SRC_A, per("兪榥", "유황")).orElseThrow().translatedText());
    }

    @Test
    void VERIFIED만_적재된다() {
        String kbVersion = kbVersion();
        TranslationCache cache = l2Cache(kbVersion, new SimpleMeterRegistry());

        // DEGRADED는 KB가 특정하지 못한 인물이 문장에 있다는 뜻 — 그 인물은 슬롯이 아니라 문면
        // 그대로 템플릿에 박히므로, 구조가 같은 다른 문장에 그 틀을 쓰면 남의 이름이 따라 나간다
        cache.storeL2(SRC_A, per("兪榥", "유황"), translated(TRANS_A), QualityGrade.DEGRADED);
        assertTrue(cache.lookupL2(SRC_B, per("金瑬", "김류")).orElseThrow().hit() == false);

        cache.storeL2(SRC_A, per("兪榥", "유황"), translated(TRANS_A), QualityGrade.REJECTED);
        assertTrue(cache.lookupL2(SRC_B, per("金瑬", "김류")).orElseThrow().hit() == false);
    }

    @Test
    void 한글명_전체형이_번역문에_없으면_적재하지_않는다() {
        TranslationCache cache = l2Cache(kbVersion(), new SimpleMeterRegistry());

        // 게이트는 이름부 일치("문회")도 반영으로 인정하지만, 템플릿화는 인명 구간을 결정론적으로
        // 특정해야 하므로 전체형만 허용한다 (ADR-009 보수적 적재 — 히트율을 버리고 안전을 산다)
        cache.storeL2("以鄭文孚爲承旨", per("鄭文孚", "정문부"),
                translated("문회를 승지로 삼았다."), QualityGrade.VERIFIED);

        assertTrue(cache.lookupL2("以金瑬爲承旨", per("金瑬", "김류")).orElseThrow().hit() == false);
    }

    @Test
    void 확정_PER이_없으면_L2_대상이_아니다() {
        MeterRegistry meters = new SimpleMeterRegistry();
        TranslationCache cache = l2Cache(kbVersion(), meters);

        // 링크 미확정(kbId 없음)·PER 아님 → 슬롯이 없으니 구조 일치를 말할 수 없다
        List<EntityDto> unlinked = List.of(
                new EntityDto("某", "PER", null, null, 0.8, "MISS", false),
                new EntityDto("承旨", "POS", null, null, 0.9, null, false));

        assertTrue(cache.lookupL2(SRC_A, unlinked).isEmpty(),
                "L2가 커버한다고 주장한 적 없는 문장이다");
        // 그래서 미스로도 세지 않는다 — 분모에 넣으면 히트율이 실제보다 낮게 보인다
        assertNull(meters.find("translation.cache.miss").counter());
    }

    @Test
    void 마커가_누락된_템플릿은_히트가_취소되고_abort로_계측된다() throws Exception {
        String kbVersion = kbVersion();
        MeterRegistry meters = new SimpleMeterRegistry();
        TranslationCache cache = l2Cache(kbVersion, meters);

        // 고장 주입: 같은 template_hash 자리에 마커 없는 템플릿을 심는다
        plantTemplate(kbVersion, SRC_B, per("金瑬", "김류"), "마커가 사라진 번역문.", 1);

        assertTrue(cache.lookupL2(SRC_B, per("金瑬", "김류")).orElseThrow().hit() == false,
                "재주입 실패는 히트가 아니다 — 전체 파이프라인으로 fallback한다 (M3 수용 기준)");
        assertEquals(1.0, meters.get("translation.cache.reinject.abort")
                .tag("reason", "structure_mismatch").counter().count());
        // 조회했고 서빙하지 못했으므로 미스다
        assertEquals(1.0, meters.get("translation.cache.miss").tag("level", "L2").counter().count());
    }

    @Test
    void 문장에_없는_슬롯이_템플릿에_남으면_히트가_취소된다() throws Exception {
        String kbVersion = kbVersion();
        MeterRegistry meters = new SimpleMeterRegistry();
        TranslationCache cache = l2Cache(kbVersion, meters);

        // 1자리 문장인데 템플릿은 2자리 — 치환 후 ⟪PER2⟫가 남는다
        plantTemplate(kbVersion, SRC_B, per("金瑬", "김류"),
                "⟪PER1⟫을 ⟪PER2⟫의 자리에 삼았다.", 2);

        assertTrue(cache.lookupL2(SRC_B, per("金瑬", "김류")).orElseThrow().hit() == false,
                "마커가 그대로 노출된 번역문을 서빙해선 안 된다");
        assertEquals(1.0, meters.get("translation.cache.reinject.abort")
                .tag("reason", "structure_mismatch").counter().count());
    }

    @Test
    void 재주입_결과가_확정_인명을_빠뜨리면_게이트가_히트를_취소한다() throws Exception {
        String kbVersion = kbVersion();
        MeterRegistry meters = new SimpleMeterRegistry();
        TranslationCache cache = l2Cache(kbVersion, meters);

        // 확정 인물 2명인데 한 명(金瑬)의 표면형이 원문에 없다 — NER이 공백을 제거한 표면형을
        // 돌려주는 경우 등. 슬롯은 1개만 생기고, 재주입 결과에는 '김류'가 없다.
        List<EntityDto> twoConfirmed = List.of(
                new EntityDto("兪榥", "PER", "P1", "유황", 0.9, "SINGLE", false),
                new EntityDto("金瑬", "PER", "P2", "김류", 0.9, "SINGLE", false));
        plantTemplate(kbVersion, SRC_A, twoConfirmed, "⟪PER1⟫을 승지로 삼았다.", 1);

        assertTrue(cache.lookupL2(SRC_A, twoConfirmed).orElseThrow().hit() == false,
                "확정 인명이 빠진 번역은 캐시에서도 나가면 안 된다 (ADR-009 배경 3)");
        assertEquals(1.0, meters.get("translation.cache.reinject.abort")
                .tag("reason", "gate_rejected").counter().count());
    }

    @Test
    void 파이프라인_버전이_바뀌면_L2도_미스가_된다() {
        String kbVersion = kbVersion();
        l2Cache(kbVersion, new SimpleMeterRegistry())
                .storeL2(SRC_A, per("兪榥", "유황"), translated(TRANS_A), QualityGrade.VERIFIED);

        // NER 재학습본 교체 — L1과 같은 이유로 L2도 갈려야 한다
        assertTrue(cache(kbVersion, "prompt-1", "onnx-2", "1", false, true, new SimpleMeterRegistry())
                .lookupL2(SRC_B, per("金瑬", "김류")).orElseThrow().hit() == false);
        // epoch 수동 손잡이
        assertTrue(cache(kbVersion, "prompt-1", "onnx-1", "2", false, true, new SimpleMeterRegistry())
                .lookupL2(SRC_B, per("金瑬", "김류")).orElseThrow().hit() == false);
    }

    @Test
    void L2_히트와_미스가_L2_라벨로_계측된다() {
        MeterRegistry meters = new SimpleMeterRegistry();
        TranslationCache cache = l2Cache(kbVersion(), meters);

        assertTrue(cache.lookupL2(SRC_B, per("金瑬", "김류")).orElseThrow().hit() == false);
        cache.storeL2(SRC_A, per("兪榥", "유황"), translated(TRANS_A), QualityGrade.VERIFIED);
        assertTrue(cache.lookupL2(SRC_B, per("金瑬", "김류")).orElseThrow().hit());

        assertEquals(1.0, meters.get("translation.cache.miss").tag("level", "L2").counter().count());
        assertEquals(1.0, meters.get("translation.cache.hit").tag("level", "L2").counter().count());
    }

    @Test
    void L2_응답은_전처리_지연을_보존하고_토큰은_비운다() {
        String kbVersion = kbVersion();
        TranslationCache cache = l2Cache(kbVersion, new SimpleMeterRegistry());
        cache.storeL2(SRC_A, per("兪榥", "유황"), translated(TRANS_A), QualityGrade.VERIFIED);
        var hit = cache.lookupL2(SRC_B, per("金瑬", "김류")).orElseThrow();

        Map<String, Long> base = new java.util.LinkedHashMap<>();
        base.put("ner", 9L);
        base.put("link", 1L);
        base.put("prompt", 2L);
        TranslationResponse resp = cache.toResponseL2(
                hit, per("金瑬", "김류"), List.of(), base, 3);

        assertEquals("L2_TEMPLATE", resp.meta().cacheHit());
        assertEquals("김류를 승지로 삼았다.", resp.translatedText());
        assertEquals("김류", resp.entities().get(0).resolvedName(),
                "엔티티는 캐시가 아니라 이번 문장의 링킹 결과여야 한다");
        assertNull(resp.meta().tokensIn(), "쓰지 않은 토큰을 계상하면 비용 SLI가 오염된다");
        assertNull(resp.meta().tokensOut());
        // NER은 실제로 돌았다 — total을 조회 시간으로 덮으면 그 사실이 지표에서 사라진다
        assertEquals(9L, resp.meta().latencyMs().get("ner"));
        assertEquals(15L, resp.meta().latencyMs().get("total"));
        assertEquals(kbVersion, resp.meta().kbVersion());
    }

    // --- 조립 도구 -------------------------------------------------------

    private String kbVersion() {
        String v = "kbtest-" + UUID.randomUUID().toString().substring(0, 8);
        usedKbVersions.add(v);
        return v;
    }

    /** L1 전용 조립 (L2는 off — 기본값과 같다). */
    private TranslationCache cache(String kbVersion, String promptVersion, String nerVersion,
                                   String epoch, boolean enabled, MeterRegistry meters) {
        return cache(kbVersion, promptVersion, nerVersion, epoch, enabled, false, meters);
    }

    private TranslationCache cache(String kbVersion, String promptVersion, String nerVersion,
                                   String epoch, boolean l1Enabled, boolean l2Enabled,
                                   MeterRegistry meters) {
        var versions = new PipelineVersions(kb(kbVersion), prompt(promptVersion), ner(nerVersion), epoch);
        return new TranslationCache(redis, versions, SLOTTER, new QualityGate(), meters,
                l1Enabled, 30, l2Enabled, 30);
    }

    /** L2 on. L1은 끈다 — L2 경로만 보려는 테스트에서 L1 히트가 끼어들면 판정이 흐려진다. */
    private TranslationCache l2Cache(String kbVersion, MeterRegistry meters) {
        return cache(kbVersion, "prompt-1", "onnx-1", "1", false, true, meters);
    }

    /** 확정 PER 1명짜리 엔티티 목록 (링크 확정 = kbId·resolvedName 있음). */
    private static List<EntityDto> per(String surface, String resolvedName) {
        return List.of(new EntityDto(surface, "PER", "P-" + surface, resolvedName,
                0.9, "SINGLE", false));
    }

    private static TranslationResponse translated(String text) {
        return new TranslationResponse(text, List.of(), List.of(),
                new Meta("gemini-3.1-flash-lite", "kb", "prompt", 400, 150, Map.of(), null));
    }

    /** 특정 template_hash 자리에 임의의 템플릿을 심는다 (재주입 실패 유발용 고장 주입). */
    private void plantTemplate(String kbVersion, String sourceText, List<EntityDto> entities,
                               String template, int slotCount) throws Exception {
        var slotted = SLOTTER.slotSource(sourceText, entities).orElseThrow();
        String key = CacheKeys.l2(new PipelineVersion(kbVersion, "prompt-1", "onnx-1", "1"),
                SLOTTER.templateHash(slotted));
        redis.opsForValue().set(key, new ObjectMapper().writeValueAsString(
                new CachedTemplate(template, "gemini-3.1-flash-lite", slotCount, "t")));
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
