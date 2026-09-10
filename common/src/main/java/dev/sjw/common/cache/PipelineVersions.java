package dev.sjw.common.cache;

import dev.sjw.common.kb.KnowledgeSource;
import dev.sjw.common.ner.EntityRecognizer;
import dev.sjw.common.translate.PromptAssembler;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** 현재 파이프라인 버전 조립. NER 버전을 아직 못 받았으면 비어 있다 — 그 경우 캐시는 쉰다. */
@Component
public class PipelineVersions {

    private static final Logger log = LoggerFactory.getLogger(PipelineVersions.class);

    private final KnowledgeSource kb;
    private final PromptAssembler prompt;
    private final EntityRecognizer ner;
    private final String epoch;

    /** 마지막으로 로그에 남긴 조합 — 값이 바뀔 때만(=캐시가 갈릴 때만) 한 줄 남긴다. */
    private volatile String logged;

    public PipelineVersions(KnowledgeSource kb, PromptAssembler prompt, EntityRecognizer ner,
                            @Value("${sjw.cache.epoch:1}") String epoch) {
        this.kb = kb;
        this.prompt = prompt;
        this.ner = ner;
        this.epoch = epoch;
    }

    public Optional<PipelineVersion> current() {
        Optional<String> nerVersion = ner.version();
        if (nerVersion.isEmpty()) {
            return Optional.empty();
        }
        PipelineVersion v = new PipelineVersion(
                kb.version(), prompt.version(), nerVersion.get(), epoch);
        String segment = v.keySegment();
        if (!segment.equals(logged)) {
            logged = segment;
            log.info("파이프라인 버전: kb={} prompt={} ner={} epoch={} — 이 조합이 캐시를 가른다",
                    v.kb(), v.prompt(), v.ner(), v.epoch());
        }
        return Optional.of(v);
    }
}
