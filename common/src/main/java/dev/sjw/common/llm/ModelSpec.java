package dev.sjw.common.llm;

import java.math.BigDecimal;

/**
 * 모델 레지스트리의 한 항목 (§10 M2.5-(2)). 이 레코드가
 * rate 버킷 키 · cost_ledger 단가 · M4 티어 매핑 · quota 풀링의 <b>단일 출처</b>다.
 *
 * @param id       provider가 인식하는 모델 id — rate 버킷 키와 원장 model 컬럼에 그대로 쓰인다
 * @param provider 어댑터 선택 키 (현재 google-genai 하나, ADR-018)
 * @param tier     M4 티어 라우팅용 (T0 저가 워크호스 / T1 고품질)
 * @param rpd      무료 일일 quota. 실측된 값만 기입한다 — 미실측이면 null (원칙 4)
 * @param unitPriceInUsdPerMtok  counterfactual 유료 단가 (입력, USD/1M tok). 유료 제공이 없는 모델은 0
 * @param unitPriceOutUsdPerMtok counterfactual 유료 단가 (출력)
 */
public record ModelSpec(
        String id,
        String provider,
        String tier,
        Integer rpd,
        BigDecimal unitPriceInUsdPerMtok,
        BigDecimal unitPriceOutUsdPerMtok) {

    public ModelSpec {
        if (id == null || id.isBlank()) {
            throw new IllegalArgumentException("모델 id는 필수");
        }
        if (unitPriceInUsdPerMtok == null || unitPriceOutUsdPerMtok == null) {
            throw new IllegalArgumentException("단가는 필수 (유료 제공이 없으면 0으로 명시): " + id);
        }
    }
}
