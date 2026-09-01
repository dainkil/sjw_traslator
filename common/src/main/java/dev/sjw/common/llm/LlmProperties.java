package dev.sjw.common.llm;

import java.math.BigDecimal;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * yml(sjw.llm.*) 바인딩. 모델 목록·활성 모델·환율의 유일한 정의 지점.
 *
 * @param activeModel 현재 호출 대상 모델 id — 반드시 models에 존재해야 한다 (기동 시 검증)
 * @param usdKrw      원화 환산 환율. cost-model.md와 같은 파라미터 (추정)
 * @param models      레지스트리 전체
 */
@ConfigurationProperties("sjw.llm")
public record LlmProperties(String activeModel, BigDecimal usdKrw, List<ModelSpec> models) {
}
