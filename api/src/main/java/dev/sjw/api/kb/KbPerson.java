package dev.sjw.api.kb;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record KbPerson(
        @JsonProperty("한글_명") String hangulName,
        @JsonProperty("한자_명") String hanjaName,
        @JsonProperty("본관_표준") String clanOrigin,
        @JsonProperty("활동_시작") Integer activeFrom,
        @JsonProperty("활동_종료") Integer activeTo,
        @JsonProperty("관직_리스트") List<String> offices
) {
    public int activeFromOrZero() {
        return activeFrom == null ? 0 : activeFrom;
    }
}
