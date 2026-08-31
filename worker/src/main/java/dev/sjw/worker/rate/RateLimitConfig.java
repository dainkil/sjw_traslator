package dev.sjw.worker.rate;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** yml(sjw.rate.*) → {@link RateLimitProperties} 바인딩. 기본값은 여기 한 곳에만 둔다. */
@Configuration
public class RateLimitConfig {

    @Bean
    public RateLimitProperties rateLimitProperties(
            @Value("${sjw.rate.initial-rpm:20}") int initialRpm,
            @Value("${sjw.rate.min-rpm:2}") int minRpm,
            @Value("${sjw.rate.max-rpm:60}") int maxRpm,
            @Value("${sjw.rate.burst-seconds:10}") int burstSeconds,
            @Value("${sjw.rate.decrease-factor:0.5}") double decreaseFactor,
            @Value("${sjw.rate.successes-to-increase:5}") int successesToIncrease,
            @Value("${sjw.rate.increase-step:1}") int increaseStep,
            @Value("${sjw.rate.max-wait-ms:120000}") long maxWaitMs) {
        return new RateLimitProperties(initialRpm, minRpm, maxRpm, burstSeconds,
                decreaseFactor, successesToIncrease, increaseStep, maxWaitMs);
    }
}
