package dev.sjw.api.tenant;

import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class TenantErrorHandler {

    @ExceptionHandler(TenantGuard.UnknownApiKeyException.class)
    public ResponseEntity<Map<String, Object>> unknownKey() {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(Map.of("error", "UNKNOWN_API_KEY"));
    }

    @ExceptionHandler(TenantGuard.DailyLimitExceededException.class)
    public ResponseEntity<Map<String, Object>> dailyLimit(TenantGuard.DailyLimitExceededException e) {
        return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS)
                .body(Map.of("error", "TENANT_DAILY_LIMIT", "dailyCallLimit", e.limit));
    }
}
