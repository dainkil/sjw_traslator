package dev.sjw.worker.failure;

import dev.sjw.common.translate.LlmParseException;
import java.util.Locale;
import org.springframework.stereotype.Component;

/**
 * 예외 → ErrorClass. HTTP 코드가 같아도(429) 본문 메시지로 갈라야 한다 —
 * 지출 상한/일일 quota/순간 rate가 전부 429로 온다 (2026-08-31 실측, docs/troubleshooting.md §2).
 */
@Component
public class FailureClassifier {

    public ErrorClass classify(Throwable e) {
        if (find(e, LlmParseException.class) != null) {
            return ErrorClass.PARSE_ERROR;
        }
        String msg = messages(e).toLowerCase(Locale.ROOT);

        if (msg.contains("429") || msg.contains("resource_exhausted")) {
            if (msg.contains("spending cap")) {
                return ErrorClass.SPEND_CAP;
            }
            if (msg.contains("perday") || msg.contains("per day")) {
                return ErrorClass.QUOTA_DAILY;
            }
            return ErrorClass.RATE_LIMITED;
        }
        if (msg.contains("404") || msg.contains("not_found") || msg.contains("no longer available")) {
            return ErrorClass.MODEL_UNAVAILABLE;
        }
        if (msg.contains("503") || msg.contains("unavailable") || msg.contains("500")
                || msg.contains("internal")) {
            return ErrorClass.SERVER_ERROR;
        }
        if (msg.contains("timed out") || msg.contains("timeout")) {
            return ErrorClass.TIMEOUT;
        }
        if (msg.contains("safety") || msg.contains("blocked") || msg.contains("prohibited")) {
            return ErrorClass.CONTENT_FILTERED;
        }
        return ErrorClass.UNKNOWN;
    }

    private static String messages(Throwable e) {
        StringBuilder sb = new StringBuilder();
        for (Throwable t = e; t != null; t = t.getCause()) {
            sb.append(t.getClass().getSimpleName()).append(' ')
              .append(String.valueOf(t.getMessage())).append(' ');
            if (t == t.getCause()) {
                break;
            }
        }
        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    private static <T extends Throwable> T find(Throwable e, Class<T> type) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            if (type.isInstance(t)) {
                return (T) t;
            }
            if (t == t.getCause()) {
                break;
            }
        }
        return null;
    }
}
