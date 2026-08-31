package dev.sjw.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication(scanBasePackages = {"dev.sjw.api", "dev.sjw.common"})
public class SjwApiApplication {

    public static void main(String[] args) {
        SpringApplication.run(SjwApiApplication.class, args);
    }
}
