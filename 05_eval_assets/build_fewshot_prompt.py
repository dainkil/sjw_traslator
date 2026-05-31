"""
다른 왕조(영조 U0) 번역문을 style 예시로 넣어
Gemma가 인조 어투로 번역하도록 유도하는 few-shot 프롬프트 생성
"""
import xml.etree.ElementTree as ET
import re
import json
import random

random.seed(42)

# 한자 괄호 제거: 창덕궁(昌德宮) → 창덕궁
def clean_trans(text):
    text = re.sub(r'\([^\)]*[一-鿿][^\)]*\)', '', text)  # (한자 포함 괄호) 제거
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# U0 파일에서 번역문 수집
u0_files = [
    "SJW_Corpus_Final/sjw_U0_A00.xml",
    "SJW_Corpus_Final/sjw_U0_A01.xml",
    "SJW_Corpus_Final/sjw_U0_A02.xml",
    "SJW_Corpus_Final/sjw_U0_A03.xml",
    "SJW_Corpus_Final/sjw_U0_A04.xml",
]

samples = []
for fp in u0_files:
    tree = ET.parse(fp)
    root = tree.getroot()
    for a in root.findall(".//article"):
        t = a.find("translation")
        if t is None: continue
        txt = clean_trans((t.text or "").strip())
        # 너무 짧거나 긴 것 제외, 한자 많이 남은 것 제외
        if 20 <= len(txt) <= 150:
            hanja_ratio = len(re.findall(r'[一-鿿]', txt)) / len(txt)
            if hanja_ratio < 0.1:
                samples.append(txt)

random.shuffle(samples)
print(f"수집된 U0 번역 샘플: {len(samples)}개")
print("\n예시 5개:")
for s in samples[:5]:
    print(" ", s)

# few-shot 예시 5개 선택
FEWSHOT_EXAMPLES = samples[:5]

PROMPT_WITH_STYLE = """다음은 조선시대 한문 번역 예시입니다. 이 어투와 문체를 참고하여 번역하세요.

[번역 예시]
{examples}

위 문체로 다음 한문을 현대 한국어로 번역하세요. 번역문만 출력하세요:

{text}"""

examples_str = "\n".join(f"- {e}" for e in FEWSHOT_EXAMPLES)
print("\n--- 프롬프트 미리보기 ---")
print(PROMPT_WITH_STYLE.format(examples=examples_str, text="上在昌德宮。停常參經筵。"))

# 저장
out = {
    "fewshot_examples": FEWSHOT_EXAMPLES,
    "prompt_template": PROMPT_WITH_STYLE,
}
with open("eval_assets/fewshot_config.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\n저장: eval_assets/fewshot_config.json")
