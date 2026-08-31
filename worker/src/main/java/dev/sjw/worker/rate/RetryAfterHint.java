package dev.sjw.worker.rate;

import java.time.Duration;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 429 응답 본문에 실려 오는 재시도 지연 힌트를 뽑는다.
 *
 * "고정 상수 금지"(§6)의 연장선: 백오프 길이를 우리가 추측하는 것보다 provider가 알려준 값이
 * 항상 낫다. Gemini는 두 형태로 준다 — 사람용 문장("Please retry in 55.6s")과
 * RetryInfo 필드("retryDelay": "55s"). 둘 다 실측 로그에서 확인된 형태다.
 */
public final class RetryAfterHint {

    /** 힌트가 비정상적으로 길면(잘못 파싱했거나 provider 이상) 이 값으로 자른다. */
    private static final Duration MAX = Duration.ofMinutes(5);

    private static final Pattern[] PATTERNS = {
        Pattern.compile("retry\\s+in\\s+([0-9]+(?:\\.[0-9]+)?)\\s*s", Pattern.CASE_INSENSITIVE),
        Pattern.compile("retry[_-]?delay\"?\\s*[:=]\\s*\"?([0-9]+(?:\\.[0-9]+)?)\\s*s",
                Pattern.CASE_INSENSITIVE),
    };

    private RetryAfterHint() {}

    public static Optional<Duration> parse(Throwable e) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            Optional<Duration> d = parse(t.getMessage());
            if (d.isPresent()) {
                return d;
            }
            if (t == t.getCause()) {
                break;
            }
        }
        return Optional.empty();
    }

    public static Optional<Duration> parse(String message) {
        if (message == null) {
            return Optional.empty();
        }
        for (Pattern p : PATTERNS) {
            Matcher m = p.matcher(message);
            if (m.find()) {
                double seconds = Double.parseDouble(m.group(1));
                Duration d = Duration.ofMillis(Math.round(seconds * 1000));
                return Optional.of(d.compareTo(MAX) > 0 ? MAX : d);
            }
        }
        return Optional.empty();
    }
}
