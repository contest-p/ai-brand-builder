import os
import base64
from dotenv import load_dotenv
from openai import OpenAI

# .env 파일 읽기
load_dotenv()

# OpenAI API 키 가져오기
api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise ValueError("OPENAI_API_KEY가 .env에 없습니다.")

# OpenAI 클라이언트 생성
client = OpenAI(api_key=api_key)

# 이미지 생성
result = client.images.generate(
    model="gpt-image-1",
    prompt=(
        "Create a simple minimalist logo for an eco-friendly cosmetics brand "
        "called Blooming. Use a clean green color palette, "
        "with a pure white background. Professional brand logo."
    ),
    size="1024x1024",
    quality="low",
    output_format="png",
)

# 생성된 이미지 저장
image_data = base64.b64decode(result.data[0].b64_json)

with open("test_logo.png", "wb") as f:
    f.write(image_data)

print("이미지 생성 완료!")
print("저장 위치: test_logo.png")