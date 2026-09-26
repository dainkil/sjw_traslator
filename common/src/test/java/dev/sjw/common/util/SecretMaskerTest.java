package dev.sjw.common.util;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;

import org.junit.jupiter.api.Test;

class SecretMaskerTest {

    private static final String GOOGLE_KEY = "AIza" + "a".repeat(35);

    @Test
    void 알려진_키는_형태와_무관하게_지운다() {
        assertEquals("rejected: ***", SecretMasker.mask("rejected: my-odd-key", "my-odd-key"));
    }

    @Test
    void Google_API_키_형태와_URL_파라미터를_지운다() {
        String masked = SecretMasker.mask("POST /v1beta/models/m:generate?key=secret123&alt=sse "
                + "header " + GOOGLE_KEY, null);
        assertFalse(masked.contains(GOOGLE_KEY), masked);
        assertFalse(masked.contains("secret123"), masked);
        assertEquals("POST /v1beta/models/m:generate?key=***&alt=sse header ***", masked);
    }

    @Test
    void null과_키_없는_문자열은_그대로() {
        assertNull(SecretMasker.mask(null, "k"));
        assertEquals("503 UNAVAILABLE", SecretMasker.mask("503 UNAVAILABLE", null));
    }
}
