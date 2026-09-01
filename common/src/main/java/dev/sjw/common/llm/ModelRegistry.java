package dev.sjw.common.llm;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 모델 레지스트리 — 설정(sjw.llm.models)으로만 채워진다. 코드에 모델 지식을 두지 않는 것이
 * "모델 교체 = 설정 변경"(M2.5 수용 기준 3)의 성립 조건이다.
 */
public class ModelRegistry {

    /** 원장 1행에 들어갈 비용 산출 결과. 무료 티어 운영이므로 실지출이 아니라 counterfactual 유료 환산이다 (ADR-016). */
    public record Cost(BigDecimal unitPriceIn, BigDecimal unitPriceOut, BigDecimal krw) {}

    private final Map<String, ModelSpec> byId = new LinkedHashMap<>();
    private final ModelSpec active;
    private final BigDecimal usdKrw;

    public ModelRegistry(LlmProperties props) {
        if (props.models() == null || props.models().isEmpty()) {
            throw new IllegalStateException("sjw.llm.models가 비어 있음 — 레지스트리 없이는 기동하지 않는다");
        }
        for (ModelSpec m : props.models()) {
            if (byId.put(m.id(), m) != null) {
                throw new IllegalStateException("모델 id 중복: " + m.id());
            }
        }
        this.active = require(props.activeModel());
        this.usdKrw = props.usdKrw() == null ? BigDecimal.valueOf(1400) : props.usdKrw();
    }

    public ModelSpec active() {
        return active;
    }

    public ModelSpec require(String id) {
        ModelSpec m = byId.get(id);
        if (m == null) {
            throw new IllegalStateException(
                    "레지스트리에 없는 모델: " + id + " (등록: " + byId.keySet() + ")");
        }
        return m;
    }

    public List<ModelSpec> all() {
        return List.copyOf(byId.values());
    }

    /** 토큰 수가 null(응답 메타 소실)이면 0으로 계산 — 원장에 행은 반드시 남긴다. */
    public Cost cost(String modelId, Integer tokensIn, Integer tokensOut) {
        ModelSpec m = require(modelId);
        BigDecimal in = BigDecimal.valueOf(tokensIn == null ? 0 : tokensIn);
        BigDecimal out = BigDecimal.valueOf(tokensOut == null ? 0 : tokensOut);
        BigDecimal mtok = BigDecimal.valueOf(1_000_000);
        BigDecimal usd = in.multiply(m.unitPriceInUsdPerMtok()).add(out.multiply(m.unitPriceOutUsdPerMtok()))
                .divide(mtok, 10, RoundingMode.HALF_UP);
        return new Cost(m.unitPriceInUsdPerMtok(), m.unitPriceOutUsdPerMtok(),
                usd.multiply(usdKrw).setScale(4, RoundingMode.HALF_UP));
    }
}
