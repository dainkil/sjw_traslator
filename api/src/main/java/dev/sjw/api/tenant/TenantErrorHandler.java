package dev.sjw.api.tenant;

import java.util.Map;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 테넌트 문(401/403/429). {@code LlmErrorHandler}의 RuntimeException 포괄 처리보다 먼저 선다.
 * Content-Type을 못 박는 이유: SSE 요청(Accept: text/event-stream)에서도 JSON 본문으로 거절이 나가야 한다.
 */
@RestControllerAdvice
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TenantErrorHandler {

    @ExceptionHandler(TenantGuard.UnknownApiKeyException.class)
    public ResponseEntity<Map<String, Object>> unknownKey() {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED).contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("error", "UNKNOWN_API_KEY"));
    }

    @ExceptionHandler(TenantGuard.ApiKeyRequiredException.class)
    public ResponseEntity<Map<String, Object>> apiKeyRequired() {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED).contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("error", "API_KEY_REQUIRED"));
    }

    @ExceptionHandler(TenantGuard.OperatorAccessRequiredException.class)
    public ResponseEntity<Map<String, Object>> operatorAccessRequired() {
        return ResponseEntity.status(HttpStatus.FORBIDDEN).contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("error", "OPERATOR_ACCESS_REQUIRED"));
    }

    @ExceptionHandler(TenantGuard.ByokRequiredException.class)
    public ResponseEntity<Map<String, Object>> byokRequired() {
        return ResponseEntity.status(HttpStatus.FORBIDDEN).contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("error", "BYOK_REQUIRED",
                        "hint", "캐시에 없는 문장은 X-Llm-Key 헤더(본인 Gemini API 키)가 필요합니다"));
    }

    @ExceptionHandler(TenantGuard.DailyLimitExceededException.class)
    public ResponseEntity<Map<String, Object>> dailyLimit(TenantGuard.DailyLimitExceededException e) {
        return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS).contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("error", "TENANT_DAILY_LIMIT", "dailyCallLimit", e.limit));
    }
}
