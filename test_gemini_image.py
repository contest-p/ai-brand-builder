import os
import base64
from dotenv import load_dotenv
from google import genai

# 프로젝트 폴더의 .env 파일을 읽는다.
load_dotenv()

# .env에서 Gemini API 키를 가져온다.
api_key = os.getenv("GEMINI_API_KEY")

# API 키가 없으면 실행을 중단한다.
if not api_key:
    raise ValueError("GEMINI_API_KEY가 .env에 없습니다.")

# 가져온 API 키로 Gemini 클라이언트를 만든다.
client = genai.Client(api_key=api_key)

# 이미지 생성 요청
interaction = client.interactions.create(
    model="gemini-3.1-flash-image",
    input="Create a simple minimalist leaf logo on a pure white background."
)

# 생성된 이미지를 PNG 파일로 저장한다.
with open("test_logo.png", "wb") as f:
    f.write(base64.b64decode(interaction.output_image.data))

print("이미지 생성 완료: test_logo.png")