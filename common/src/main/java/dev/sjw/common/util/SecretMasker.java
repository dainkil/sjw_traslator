package dev.sjw.common.util;

import java.util.regex.Pattern;

/**
 * 로그·응답에 실릴 문자열에서 LLM 키를 가린다 (§8.2 "BYOK 키는 저장·로깅 금지").
 * provider 예외 메시지가 요청 URL(?key=...)이나 헤더를 되비출 수 있으므로 알려진 키 값과
 * Google API 키 형태(AIza + 35자) 둘 다 지운다.
 */
public final class SecretMasker {

    private static final Pattern GOOGLE_API_KEY = Pattern.compile("AIza[0-9A-Za-z_\\-]{35}");
    private static final Pattern KEY_PARAM = Pattern.compile("(?i)([?&]key=)[^&\\s\"']+");
    private static final String MASK = "***";

    private SecretMasker() {}

    /** @param knownKey 이 요청에서 받은 키 (없으면 null) — 형태와 무관하게 값 자체를 지운다 */
    public static String mask(String text, String knownKey) {
        if (text == null) {
            return null;
        }
        String out = text;
        if (knownKey != null && !knownKey.isBlank()) {
            out = out.replace(knownKey, MASK);
        }
        out = GOOGLE_API_KEY.matcher(out).replaceAll(MASK);
        return KEY_PARAM.matcher(out).replaceAll("$1" + MASK);
    }
}
