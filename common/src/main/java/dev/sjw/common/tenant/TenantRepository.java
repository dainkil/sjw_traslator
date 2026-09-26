package dev.sjw.common.tenant;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Optional;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/** 발급형 API 키(X-Api-Key)는 해시로만 저장·대조한다. 평문 키는 DB에 없다. */
@Repository
public class TenantRepository {

    private static final RowMapper<Tenant> MAPPER = (rs, n) -> new Tenant(rs.getString("id"),
            rs.getString("display_name"), rs.getInt("daily_call_limit"), rs.getBoolean("operator_access"));

    private final JdbcClient jdbc;

    public TenantRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<Tenant> findByApiKey(String apiKey) {
        return jdbc.sql("""
                SELECT id, display_name, daily_call_limit, operator_access FROM tenant WHERE api_key_hash = ?
                """)
                .params(sha256(apiKey))
                .query(MAPPER)
                .optional();
    }

    public Tenant defaultTenant() {
        return jdbc.sql("SELECT id, display_name, daily_call_limit, operator_access FROM tenant WHERE id = ?")
                .params(Tenant.DEFAULT_ID)
                .query(MAPPER)
                .single();
    }

    public static String sha256(String value) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(md.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
