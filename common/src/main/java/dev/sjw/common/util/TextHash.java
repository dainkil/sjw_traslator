package dev.sjw.common.util;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.text.Normalizer;
import java.util.HexFormat;

public final class TextHash {

    private TextHash() {}

    /** L1 캐시/멱등의 기준 해시: NFC 정규화 + 공백 제거 후 SHA-256. */
    public static String normalizedHash(String text) {
        String normalized = Normalizer.normalize(text, Normalizer.Form.NFC)
                .replaceAll("\\s+", "");
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(md.digest(normalized.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
