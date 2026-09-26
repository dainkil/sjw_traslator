package dev.sjw.api.tenant;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import dev.sjw.common.tenant.Tenant;
import dev.sjw.common.tenant.TenantRepository;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;

/** 공개 모드 off(로컬 기본값)의 동작이 하드닝 전과 같은가 — 로컬 개발·데모 스크립트 무변경의 근거. */
class TenantGuardTest {

    private static final Tenant DEFAULT = new Tenant(Tenant.DEFAULT_ID, "운영자 기본", 1000, true);

    private static TenantGuard guard(boolean publicMode) {
        TenantRepository tenants = mock(TenantRepository.class);
        when(tenants.defaultTenant()).thenReturn(DEFAULT);
        return new TenantGuard(tenants, mock(StringRedisTemplate.class), publicMode);
    }

    @Test
    void 로컬_모드는_키_없으면_default이고_BYOK도_요구하지_않는다() {
        var g = guard(false);
        assertEquals(DEFAULT, g.resolve(null));
        assertEquals(DEFAULT, g.resolve(" "));
        assertDoesNotThrow(() -> g.requireByok(null));
        assertDoesNotThrow(() -> g.requireOperatorAccess(DEFAULT));   // V5가 default에 operator_access를 준다
    }

    @Test
    void 공개_모드는_키_없으면_401_BYOK_없으면_403() {
        var g = guard(true);
        assertThrows(TenantGuard.ApiKeyRequiredException.class, () -> g.resolve(null));
        assertThrows(TenantGuard.ByokRequiredException.class, () -> g.requireByok(""));
        assertDoesNotThrow(() -> g.requireByok("user-key"));
        assertThrows(TenantGuard.OperatorAccessRequiredException.class,
                () -> g.requireOperatorAccess(new Tenant("alice", "alice", 50, false)));
    }
}
