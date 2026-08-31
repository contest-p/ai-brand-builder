"""
brand_generator.py
터미널에서 브리프 JSON을 받아, 5단계로 브랜드 결과물을 만들고
마지막에 brand_result.json으로 저장하는 CLI 프로그램입니다.
"""

import json  # JSON 파일을 읽고, 결과를 JSON으로 저장할 때 사용
import os  # 환경변수(API 키)와 파일 경로를 다룰 때 사용
import sys  # 프로그램 종료(sys.exit)에 사용
import base64  # 이미지 생성 API가 돌려주는 b64_json을 실제 이미지 파일로 바꿀 때 사용
import time  # API 재시도 전 대기 시간에 사용
from datetime import datetime  # 에러 발생 시간을 기록할 때 사용
import requests  # 이미지 생성 API에 직접 HTTP 요청을 보낼 때 사용
from pathlib import Path  # 폴더/파일 경로를 다루기 쉽게 해주는 도구
import openai
import matplotlib.pyplot as plt  # 컬러 팔레트를 이미지로 그릴 때 사용
import matplotlib.patches as patches  # 네모 박스(사각형)를 그릴 때 사용


# ---------------------------------------------------------------------------
# 1) .env 파일 확인 후 환경변수로 넣기
# ---------------------------------------------------------------------------
def load_env_file(env_path=".env"):
    """
    .env 파일을 한 줄씩 읽어서 KEY=VALUE 를 os.environ 에 넣습니다.

    반환:
      - 파일이 없으면 None
      - 있으면 KEY=VALUE 줄의 개수 (0일 수도 있음)
    """
    path = Path(env_path)

    if not path.exists():
        return None

    pair_count = 0

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]

            if not key or not value:
                continue

            pair_count += 1

            if key not in os.environ:
                os.environ[key] = value

    return pair_count


def get_api_key():
    """
    .env 가 있는지, 그 안에 KEY=값 줄이 최소 하나 있는지만 확인합니다.
    파일이 없거나 유효한 줄이 하나도 없으면 안내 후 프로그램을 종료합니다.
    """
    pair_count = load_env_file(".env")

    if pair_count is None:
        print(".env 파일을 찾지 못했습니다.")
        print("프로젝트 폴더에 .env 파일을 만들고, 아래처럼 한 줄 이상 넣어 주세요.")
        print()
        print("    키이름=값")
        print()
        print("키 이름은 각자 사용하는 API에 맞게 정하면 됩니다.")
        print("키는 외부에 공유하지 마세요. .env는 git에 올리지 않는 것이 안전합니다.")
        sys.exit(1)

    if pair_count < 1:
        print(".env 파일은 있지만, KEY=값 형태의 줄이 없습니다.")
        print("빈 줄과 # 주석을 제외하고, 이름=값 이 최소 한 줄은 있어야 합니다.")
        print()
        print("    예) 키이름=붙여넣을_값")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 2) 사용자 입력 / 브리프 JSON 읽기
# ---------------------------------------------------------------------------
REQUIRED_BRIEF_FIELDS = ("industry", "target", "keywords")
OPTIONAL_BRIEF_FIELDS = ("tone", "competitors", "notes")


def ask_paths():
    """
    터미널에서 두 가지 경로를 입력받습니다.
    - 브리프 JSON 경로: 필수
    - 출력 폴더: 엔터만 치면 ./output
    """
    print("=== AI 브랜드 제너레이터 ===")
    print()

    brief_path = input("브리프 JSON 파일 경로를 입력하세요: ").strip()
    if not brief_path:
        print("브리프 JSON 경로는 필수입니다. 프로그램을 종료합니다.")
        sys.exit(1)

    output_dir = input("출력 폴더 경로를 입력하세요 (엔터 = ./output): ").strip()
    if not output_dir:
        output_dir = "./output"

    return Path(brief_path), Path(output_dir)


def load_brief(brief_path):
    """
    JSON 파일을 읽어 딕셔너리로 반환합니다.
    파일이 없거나 JSON이 깨졌거나, 필수 필드가 없으면 안내 후 종료합니다.
    """
    if not brief_path.exists():
        print(f"파일을 찾을 수 없습니다: {brief_path}")
        sys.exit(1)

    try:
        with brief_path.open("r", encoding="utf-8") as f:
            brief = json.load(f)
    except json.JSONDecodeError:
        print("JSON 형식이 올바르지 않습니다. 쉼표, 따옴표, 중괄호를 확인해 주세요.")
        sys.exit(1)

    if not isinstance(brief, dict):
        print("브리프 JSON의 최상위는 객체(중괄호 {})여야 합니다.")
        sys.exit(1)

    missing = [field for field in REQUIRED_BRIEF_FIELDS if not brief.get(field)]
    if missing:
        print("브리프에 필수 필드가 없습니다:", ", ".join(missing))
        print("필수: industry, target, keywords")
        print("선택: tone, competitors, notes")
        sys.exit(1)

    return brief


# ---------------------------------------------------------------------------
# 3) 팀원 공통: API 호출을 안전하게 감싸는 함수 / API 키 에러 판별
# ---------------------------------------------------------------------------
_STEP_NAME_BY_FUNC = {
    "generate_naming": "네이밍",
    "generate_slogan": "슬로건",
    "generate_story": "스토리",
    "generate_color_palette": "컬러",
    "generate_logo": "로고",
}

# 단계별 에러를 brand_result.json에 저장하기 위한 에러 기록 목록
ERROR_HISTORY = []


def _record_error(step, message):
    """
    단계별 오류를 결과 JSON에 저장하기 위해 기록합니다.
    """
    ERROR_HISTORY.append(
        {
            "step": step,
            "message": str(message),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
    )


def _looks_like_api_key_error(error):
    """
    OpenAI / Anthropic / HTTP 등 라이브러리가 달라도
    '키가 없거나 잘못됐다'는 신호를 최대한 같은 방식으로 알아챈다.
    """
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(error, "status", None)
    if status in (401, 403):
        return True

    code = str(getattr(error, "code", "") or getattr(error, "type", "")).lower()
    if "api_key" in code or "apikey" in code or code in (
        "invalid_api_key",
        "authentication_error",
    ):
        return True

    class_name = type(error).__name__.lower()
    if "auth" in class_name or "permission" in class_name:
        return True

    message = str(error).lower()
    key_hints = (
        "api key",
        "api_key",
        "apikey",
        "invalid api",
        "incorrect api",
        "unauthorized",
        "authentication",
        "invalid_api_key",
        "incorrect api key",
        "no api key",
        "missing api",
        "api 키",
        "인증",
    )
    return any(hint in message for hint in key_hints)


def _report_error(label, error):
    """
    API 키 문제인지 아닌지 판별해서 알맞은 메시지를 출력하는 공통 헬퍼.
    generate_naming / generate_slogan / generate_story / generate_color_palette가
    모두 이 함수를 통해 에러를 출력한다 (요구사항: API 키 오류는 명확하게 안내).
    """
    if _looks_like_api_key_error(error):
        print("API 키를 확인해주세요")
    else:
        print(f"{label} 생성 중 오류가 발생했습니다: {error}")


def _guess_step_name(func, step_name):
    if step_name:
        return step_name

    func_name = getattr(func, "__name__", "") or ""
    if func_name in _STEP_NAME_BY_FUNC:
        return _STEP_NAME_BY_FUNC[func_name]

    if func_name.startswith("generate_"):
        return func_name[len("generate_"):]

    return func_name or "API"


def safe_api_call(func, *args, step_name=None, **kwargs):
    """
    어떤 함수든(API 호출, 내부 헬퍼 등) 받아서 실행하고,
    실패해도 프로그램이 죽지 않게 막아 주는 공통 함수.
    """
    label = _guess_step_name(func, step_name)

    try:
        return func(*args, **kwargs)
    except Exception as error:
        _report_error(label, error)
        return None


# ---------------------------------------------------------------------------
# 4) 5단계 생성 함수
# ---------------------------------------------------------------------------
def _strip_code_fence(text):
    """
    AI 응답이 ```json ... ``` 처럼 코드블록으로 감싸져 오는 경우가 있어서,
    앞뒤의 ``` 표시를 제거하고 순수 JSON 텍스트만 남긴다.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _brief_prompt_lines(brief):
    """네이밍/슬로건/스토리/컬러 프롬프트에 공통으로 쓰는 브리프 요약 문자열."""
    industry = brief.get("industry", "")
    target = brief.get("target", "")
    keywords = brief.get("keywords", [])
    tone = brief.get("tone", "")

    lines = f"업종: {industry}\n타겟: {target}\n키워드: {', '.join(keywords)}"
    if tone:
        lines += f"\n톤앤매너: {tone}"
    return lines


def generate_naming(brief):
    """
    입력: brief (딕셔너리) — industry, target, keywords 등
    출력: 브랜드명 후보 리스트 (실패 시 빈 리스트)
          각 항목은 {"name": 한글명, "name_en": 영문명, "meaning": 의미/유래}

    * 보너스 과제(다국어 네이밍 지원): 한글 네이밍과 함께 영문 네이밍을
      동시에 생성하도록 name_en 필드를 추가했다.
    """
    client = openai.OpenAI()

    system_prompt = (
        "당신은 전문 브랜드 네이밍 컨설턴트입니다. "
        "주어진 브랜드 정보를 바탕으로 브랜드명 후보 3~5개를 만들어주세요. "
        "각 후보마다 한글 브랜드명과, 그에 대응하는 영문 브랜드명(발음 표기가 아니라 "
        "실제 영문 브랜드명으로 사용할 수 있는 이름)을 함께 만들고, 이름의 의미/유래도 설명해주세요. "
        "다른 설명, 인사말, 코드블록 표시 없이 아래 JSON 형식으로만 답하세요.\n"
        '[{"name": "한글 브랜드명", "name_en": "영문 브랜드명", "meaning": "이름의 의미/유래 설명"}, ...]'
    )

    user_prompt = _brief_prompt_lines(brief)

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-5.4-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            content = _strip_code_fence(response.choices[0].message.content)
            naming_list = json.loads(content)

            if not isinstance(naming_list, list):
                raise ValueError("네이밍 응답이 리스트 형식이 아닙니다.")

            if not 3 <= len(naming_list) <= 5:
                raise ValueError("네이밍 후보는 3~5개여야 합니다.")

            for item in naming_list:
                if not isinstance(item, dict):
                    raise ValueError("네이밍 후보 항목이 객체 형식이 아닙니다.")
                if not item.get("name"):
                    raise ValueError("네이밍 후보에 name 필드가 없습니다.")
                if not item.get("name_en"):
                    raise ValueError("네이밍 후보에 name_en 필드가 없습니다.")
                if not item.get("meaning"):
                    raise ValueError("네이밍 후보에 meaning 필드가 없습니다.")

            return naming_list

        except json.JSONDecodeError:
            error_message = "네이밍 응답이 올바른 JSON 형식이 아닙니다."
        except Exception as error:
            error_message = str(error)

        if attempt == 0:
            print("네이밍 응답을 검증하지 못했습니다. 수정 요청 후 다시 생성합니다.")
            user_prompt = (
                _brief_prompt_lines(brief)
                + "\n\n이전 응답에 문제가 있었습니다. "
                "브랜드명 후보를 정확히 3~5개 생성하고, "
                "각 항목에 name, name_en, meaning 필드를 모두 포함하여 "
                "지정한 JSON 형식으로만 다시 답하세요."
            )
        else:
            print(error_message)
            return []

    return []


def generate_slogan(brief):
    """
    입력: brief (딕셔너리)
    출력: 슬로건 문자열 리스트 (실패 시 빈 리스트)
    """
    client = openai.OpenAI()

    system_prompt = (
        "당신은 전문 카피라이터입니다. "
        "주어진 브랜드 정보를 바탕으로 슬로건/태그라인 3개를 만들어주세요. "
        "다른 설명, 인사말, 코드블록 표시 없이 아래 JSON 형식으로만 답하세요.\n"
        '["슬로건1", "슬로건2", "슬로건3"]'
    )

    user_prompt = _brief_prompt_lines(brief)
    if brief.get("tone"):
        user_prompt += " (반드시 이 톤앤매너를 반영해줘)"

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-5.4-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            content = _strip_code_fence(response.choices[0].message.content)
            slogan_list = json.loads(content)

            if not isinstance(slogan_list, list):
                raise ValueError("슬로건 응답이 리스트 형식이 아닙니다.")

            if len(slogan_list) != 3:
                raise ValueError("슬로건은 정확히 3개여야 합니다.")

            if not all(isinstance(item, str) and item.strip() for item in slogan_list):
                raise ValueError("슬로건은 비어 있지 않은 문자열이어야 합니다.")

            return slogan_list

        except json.JSONDecodeError:
            error_message = "슬로건 응답이 올바른 JSON 형식이 아닙니다."
        except Exception as error:
            error_message = str(error)

        if attempt == 0:
            print("슬로건 응답을 검증하지 못했습니다. 수정 요청 후 다시 생성합니다.")
            user_prompt = (
                _brief_prompt_lines(brief)
                + "\n\n이전 응답에 문제가 있었습니다. "
                "슬로건을 정확히 3개 생성하고, "
                "다른 설명 없이 JSON 배열 형식으로만 다시 답하세요."
            )
        else:
            print(error_message)
            return []

    return []


def generate_story(brief):
    """
    입력: brief (딕셔너리) — industry, target, keywords, tone 등
    출력: 브랜드 스토리 문자열 (탄생 배경/철학/비전, 300자 내외). 실패 시 None.

    * 수정: 이전 버전은 특정 브리프(친환경 화장품 · 아토피 서사)에 맞춰
      시스템 프롬프트가 고정되어 있어 다른 업종을 넣어도 항상 같은 톤의
      스토리가 나오는 문제가 있었다. brief의 industry/target/keywords/tone을
      실제로 반영하도록 일반화했다.
    """
    client = openai.OpenAI()

    system_prompt = (
        "당신은 전문 브랜드 스토리텔러입니다. "
        "주어진 브랜드 정보(업종, 타겟, 키워드, 톤앤매너)를 바탕으로 "
        "브랜드의 탄생 배경, 철학, 비전이 담긴 브랜드 스토리를 300자 내외로 작성해주세요. "
        "다른 설명이나 인사말 없이 스토리 본문만 출력하세요."
    )

    user_prompt = _brief_prompt_lines(brief)

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-5.4-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            story = response.choices[0].message.content.strip()

            if not story:
                raise ValueError("브랜드 스토리 응답이 비어 있습니다.")

            return story

        except Exception as error:
            error_message = str(error)

        if attempt == 0:
            print("브랜드 스토리 응답을 검증하지 못했습니다. 수정 요청 후 다시 생성합니다.")
            user_prompt = (
                _brief_prompt_lines(brief)
                + "\n\n이전 응답에 문제가 있었습니다. "
                "업종, 타겟, 키워드, 톤앤매너를 반영한 브랜드 스토리를 "
                "300자 내외로 다시 작성해주세요. 다른 설명 없이 본문만 출력하세요."
            )
        else:
            _report_error("스토리", error)
            return None

    return None


def generate_color_palette(brief):
    """
    입력: brief (딕셔너리)
    출력: {"main": "#HEX", "sub": ["#HEX", "#HEX", ...]} 형태의 딕셔너리. 실패 시 None.

    * 수정: 이전 버전은 LLM을 호출하지 않고 고정된 컬러값을 그대로 반환했다.
      요구사항("LLM API를 호출하여 브랜드에 어울리는 컬러를 추천받는다")에 맞춰
      generate_naming/generate_slogan과 동일한 패턴으로 LLM 호출 + JSON 파싱으로 바꿨다.
    """
    client = openai.OpenAI()

    system_prompt = (
        "당신은 전문 브랜드 컬러 컨설턴트입니다. "
        "주어진 브랜드 정보를 바탕으로 브랜드에 어울리는 메인 컬러 1개와 "
        "서브 컬러 2~3개를 HEX 코드로 추천해주세요. "
        "다른 설명, 인사말, 코드블록 표시 없이 아래 JSON 형식으로만 답하세요.\n"
        '{"main": "#RRGGBB", "sub": ["#RRGGBB", "#RRGGBB"]}'
    )

    user_prompt = _brief_prompt_lines(brief)

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-5.4-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            content = _strip_code_fence(response.choices[0].message.content)
            color_dict = json.loads(content)

            if not isinstance(color_dict, dict) or not color_dict.get("main"):
                raise ValueError("컬러 팔레트 응답 형식이 올바르지 않습니다.")

            if not isinstance(color_dict.get("sub"), list):
                raise ValueError("컬러 팔레트의 sub가 리스트 형식이 아닙니다.")

            if not 2 <= len(color_dict["sub"]) <= 3:
                raise ValueError("서브 컬러는 2~3개여야 합니다.")

            hex_pattern = r"^#[0-9A-Fa-f]{6}$"

            import re

            if not isinstance(color_dict["main"], str) or not re.fullmatch(
                hex_pattern, color_dict["main"]
            ):
                raise ValueError("메인 컬러 HEX 형식이 올바르지 않습니다.")

            if not all(
                isinstance(color, str) and re.fullmatch(hex_pattern, color)
                for color in color_dict["sub"]
            ):
                raise ValueError("서브 컬러 HEX 형식이 올바르지 않습니다.")

            return color_dict

        except json.JSONDecodeError:
            error_message = "컬러 팔레트 응답이 올바른 JSON 형식이 아닙니다."
        except Exception as error:
            error_message = str(error)

        if attempt == 0:
            print("컬러 팔레트 응답을 검증하지 못했습니다. 수정 요청 후 다시 생성합니다.")
            user_prompt = (
                _brief_prompt_lines(brief)
                + "\n\n이전 응답에 문제가 있었습니다. "
                "main에는 정확한 #RRGGBB 형식의 HEX 코드 1개, "
                "sub에는 정확한 #RRGGBB 형식의 HEX 코드 2~3개를 넣어 "
                "지정된 JSON 형식으로만 다시 답하세요."
            )
        else:
            print(error_message)
            return None

    return None


def save_color_palette_image(color_dict, output_dir):
    """
    메인 컬러 1개 + 서브 컬러 여러 개를 가로로 나란히 놓인 네모 박스로
    그리고, 각 박스 아래에 HEX 코드를 텍스트로 표시해서 PNG로 저장한다.
    """
    if not color_dict or not isinstance(color_dict, dict):
        print("컬러 팔레트 정보가 없어 이미지를 만들 수 없습니다.")
        return None

    main_color = color_dict.get("main")
    sub_colors = color_dict.get("sub", []) or []

    if not main_color:
        print("메인 컬러가 없어 이미지를 만들 수 없습니다.")
        return None

    all_colors = [main_color] + list(sub_colors)

    box_width = 2.0
    main_box_height = 2.0
    sub_box_height = 1.5

    fig, ax = plt.subplots(figsize=(box_width * len(all_colors), 3))

    for i, hex_color in enumerate(all_colors):
        is_main = (i == 0)
        box_height = main_box_height if is_main else sub_box_height

        x = i * box_width
        y = 0

        rect = patches.Rectangle(
            (x, y),
            box_width * 0.9,
            box_height,
            facecolor=hex_color,
            edgecolor="black",
            linewidth=1,
        )
        ax.add_patch(rect)

        label = f"{hex_color}\n(Main)" if is_main else hex_color
        ax.text(
            x + (box_width * 0.9) / 2,
            -0.3,
            label,
            ha="center",
            va="top",
            fontsize=10,
        )

    ax.set_xlim(-0.2, box_width * len(all_colors))
    ax.set_ylim(-1, main_box_height + 0.5)

    ax.axis("off")
    ax.set_title("Brand Color Palette", fontsize=14, pad=15)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    image_path = output_path / "color_palette.png"

    fig.savefig(image_path, bbox_inches="tight", dpi=150)
    plt.close(fig)

    print(f"컬러 팔레트 이미지가 {image_path}에 저장되었습니다")
    return str(image_path)


def generate_logo(brief, naming_result, color_result, output_dir):
    """
    입력:
      - brief: 브리프 딕셔너리
      - naming_result: generate_naming()이 만든 이름 후보 리스트 (None/빈 리스트일 수 있음)
      - color_result: generate_color_palette()가 만든 색상 딕셔너리 (None일 수 있음)
      - output_dir: 사용자가 지정한 출력 폴더 (문자열 또는 Path)
    출력: 저장된 로고 이미지 파일 경로 리스트

    * 수정: 이전 버전은 output_dir 인자를 받지 않고 항상 "./output"에 저장해서,
      사용자가 다른 출력 폴더를 지정하면 로고만 엉뚱한 곳에 저장되는 버그가 있었다.
      이제 main()에서 넘겨준 output_dir을 그대로 사용한다.
    """
    if naming_result:
        brand_name = naming_result[0].get("name", "브랜드")
    else:
        brand_name = None

    if color_result and color_result.get("main"):
        main_color = color_result["main"]
        sub_colors = color_result.get("sub") or []
    else:
        main_color = "#CCCCCC"
        sub_colors = []

    industry = brief.get("industry", "브랜드")

    if brand_name:
        base_desc = f"'{brand_name}'라는 이름의 {industry} 브랜드를 위한 로고"
    else:
        base_desc = f"{industry} 브랜드를 위한 미니멀한 로고"

    if sub_colors:
        sub_color_text = f", 보조 색상으로 {', '.join(sub_colors)}도 함께 사용"
    else:
        sub_color_text = ""

    style_prompts = [
        f"{base_desc}, 텍스트(로고타입) 위주 디자인, 메인 컬러는 {main_color}{sub_color_text}, "
        f"깔끔한 산세리프 폰트, 흰색 배경, 미니멀 스타일",
        f"{base_desc}, 브랜드명 글자 없이 심볼/아이콘 위주 디자인, "
        f"메인 컬러는 {main_color}{sub_color_text}, 흰색 배경, 미니멀 플랫 디자인",
        f"{base_desc}, 아이콘 심볼과 브랜드명 텍스트를 함께 배치한 조합형 디자인, "
        f"메인 컬러는 {main_color}{sub_color_text}, 흰색 배경, 미니멀 스타일",
    ]

    api_key = os.environ.get("IMAGE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("IMAGE_API_BASE_URL", "https://copa.codyssey.kr")

    if not api_key:
        print("이미지 생성용 API 키가 없습니다. .env를 확인해주세요.")
        _record_error("로고", "이미지 생성용 API 키가 없습니다.")
        return []

    image_url = f"{base_url}/api/v1/images"
    headers = {"Authorization": f"Bearer {api_key}"}

    # output_dir을 그대로 사용 (이전: 하드코딩된 "./output")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    saved_paths = []

    for index, prompt in enumerate(style_prompts, start=1):
        success = False

        for attempt in range(1, 4):
            try:
                response = requests.post(
                    image_url,
                    headers=headers,
                    json={
                        "model": "gpt-image-1-mini",
                        "prompt": prompt,
                        "size": "1024x1024",
                        "response_format": "b64_json",
                    },
                    timeout=60,
                )
                response.raise_for_status()

                result = response.json()
                b64_image = result["result"]["images"][0]["b64_json"]

                file_name = f"logo_{index:02d}.png"
                file_path = output_path / file_name

                with open(file_path, "wb") as f:
                    f.write(base64.b64decode(b64_image))

                saved_paths.append(str(file_path))
                print(f"  → {file_name} 저장 완료")
                success = True
                break

            except Exception as error:
                if _looks_like_api_key_error(error):
                    print(f"  → 로고 시안 {index}번: API 키를 확인해주세요")
                else:
                    print(
                        f"  → 로고 시안 {index}번 생성 중 오류가 발생했습니다: {error}"
                    )

                if attempt < 3:
                    wait_seconds = 2 ** (attempt - 1)
                    print(
                        f"  → {wait_seconds}초 후 {attempt + 1}번째 시도를 진행합니다."
                    )
                    time.sleep(wait_seconds)
                else:
                    _record_error(
                        f"로고 시안 {index}번",
                        str(error),
                    )

        if not success:
            print(f"  → {index}번 시안은 건너뛰고 계속 진행합니다.")

    return saved_paths


# ---------------------------------------------------------------------------
# 5) 한 단계를 안전하게 실행 (실패해도 프로그램은 계속)
# ---------------------------------------------------------------------------
def run_step(step_number, total_steps, title, func, *args):
    print(f"[{step_number}/{total_steps}] {title} 생성 중...")

    # API/단계 실패 시 최대 3회 재시도
    for attempt in range(1, 4):
        try:
            result = func(*args)

            # 각 생성 함수의 실패 반환값을 확인해서 재시도
            failed = (
                result is None
                or (isinstance(result, list) and len(result) == 0)
            )

            if not failed:
                return result

            if attempt < 3:
                wait_seconds = 2 ** (attempt - 1)
                print(
                    f"  → {title} 결과 생성에 실패했습니다. "
                    f"{wait_seconds}초 후 재시도합니다. "
                    f"({attempt + 1}/3)"
                )
                time.sleep(wait_seconds)
                continue

            _record_error(title, f"{title} 단계가 3회 시도 후 실패했습니다.")
            print(f"  → {title} 단계는 건너뛰고 다음 단계로 진행합니다.")
            return None

        except Exception as error:
            if _looks_like_api_key_error(error):
                print("  → API 키를 확인해주세요")
            else:
                print(f"  → {title} 단계에서 오류가 났습니다: {error}")

            if attempt < 3:
                wait_seconds = 2 ** (attempt - 1)
                print(
                    f"  → {wait_seconds}초 후 {attempt + 1}번째 시도를 진행합니다."
                )
                time.sleep(wait_seconds)
            else:
                _record_error(title, str(error))
                print("  → 이 단계는 건너뛰고 다음 단계로 진행합니다.")
                return None

    return None


# ---------------------------------------------------------------------------
# 6) 결과를 JSON 파일로 저장
# ---------------------------------------------------------------------------
def save_result(output_dir, result_dict):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    result_file = output_path / "brand_result.json"

    with result_file.open("w", encoding="utf-8") as f:
        json.dump(result_dict, f, ensure_ascii=False, indent=2)

    print(f"결과가 {result_file}에 저장되었습니다")
    return str(result_file)


# ---------------------------------------------------------------------------
# 7) 프로그램 시작점
# ---------------------------------------------------------------------------
def main():
    global ERROR_HISTORY

    # 이전 실행의 에러 기록이 남지 않도록 초기화
    ERROR_HISTORY = []

    get_api_key()

    brief_path, output_dir = ask_paths()
    brief = load_brief(brief_path)

    print()
    print("브리프를 읽었습니다. 5단계를 시작합니다.")
    print()

    naming_result = run_step(1, 5, "브랜드 네이밍", generate_naming, brief)
    slogan_result = run_step(2, 5, "슬로건", generate_slogan, brief)
    story_result = run_step(3, 5, "브랜드 스토리", generate_story, brief)
    color_result = run_step(4, 5, "컬러 팔레트", generate_color_palette, brief)

    color_palette_image_path = run_step(
        "4b", 5, "컬러 팔레트 이미지 저장", save_color_palette_image, color_result, output_dir
    )

    # 수정: output_dir을 generate_logo에 함께 전달
    logo_result = run_step(
        5,
        5,
        "로고",
        generate_logo,
        brief,
        naming_result,
        color_result,
        output_dir,
    )

    results = {
        "brief": brief,
        "naming": naming_result,
        "slogan": slogan_result,
        "story": story_result,
        "color_palette": color_result,
        "color_palette_image": color_palette_image_path,
        "logo_paths": logo_result,
        "errors": ERROR_HISTORY,
    }

    save_result(output_dir, results)


if __name__ == "__main__":
    main()