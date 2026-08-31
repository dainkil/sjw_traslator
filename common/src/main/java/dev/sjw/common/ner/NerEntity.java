package dev.sjw.common.ner;

public record NerEntity(String surface, String type, int start, int end, double score) {}
