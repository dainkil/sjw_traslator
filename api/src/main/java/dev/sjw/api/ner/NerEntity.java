package dev.sjw.api.ner;

public record NerEntity(String surface, String type, int start, int end, double score) {}
