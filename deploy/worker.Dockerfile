# worker 이미지 (M2.5-S8, ADR-022). 빌드 컨텍스트 = 저장소 루트.
FROM eclipse-temurin:21-jdk AS build
WORKDIR /src
COPY gradlew settings.gradle ./
COPY gradle gradle
COPY common common
COPY api api
COPY worker worker
RUN ./gradlew :worker:bootJar --no-daemon -q

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /src/worker/build/libs/*.jar app.jar
COPY kb kb
ENV KB_DIR=/app/kb
EXPOSE 8081
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
