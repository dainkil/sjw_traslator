package dev.sjw.common.cache;

import dev.sjw.common.translate.TranslationDtos.EntityDto;
import dev.sjw.common.translate.TranslationDtos.UncertainSpan;
import java.util.List;

/**
 * L1 캐시에 들어가는 값 (Redis JSON).
 *
 * <p>번역문만이 아니라 <b>KB 파생물(링크된 엔티티)까지 통째로</b> 담는다 — 히트가 NER 추론과
 * 링킹을 건너뛰려면 그 결과물이 값 안에 있어야 하기 때문이다 (ADR-009 배경 1).
 * {@code producedModel}은 이 번역을 실제로 만든 모델 — 키에는 없지만 값에 보존해 반환한다.
 */
public record CachedTranslation(
        String translatedText,
        List<EntityDto> entities,
        List<UncertainSpan> uncertainSpans,
        String producedModel,
        String qualityGrade,
        String storedAt) {}
