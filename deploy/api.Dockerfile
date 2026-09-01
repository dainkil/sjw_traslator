# api 이미지 (M2.5-S8, ADR-022). 빌드 컨텍스트 = 저장소 루트:
#   docker build -f deploy/api.Dockerfile .
# base 이미지는 전부 multi-arch — 배포 타겟이 ARM(Oracle Always Free A1)이어도 그대로 빌드된다.
FROM eclipse-temurin:21-jdk AS build
WORKDIR /src
COPY gradlew settings.gradle ./
COPY gradle gradle
COPY common common
COPY api api
COPY worker worker
RUN ./gradlew :api:bootJar --no-daemon -q

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /src/api/build/libs/*.jar app.jar
# KB·골든셋은 이미지에 동봉 — 컨테이너가 저장소 체크아웃 없이 자립한다
COPY kb kb
COPY eval/eval300_1925.json eval/eval300_1925.json
ENV KB_DIR=/app/kb \
    SJW_EVAL_CORPUS=/app/eval/eval300_1925.json
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
