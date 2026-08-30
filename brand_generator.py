"""
brand_generator.py
터미널에서 브리프 JSON을 받아, 5단계로 브랜드 결과물을 만들고
마지막에 brand_result.json으로 저장하는 CLI 프로그램입니다.

지금은 전체 흐름만 완성되어 있고,
실제 AI 생성 함수 5개는 pass(빈 구현) 상태입니다.
"""

import json  # JSON 파일을 읽고, 결과를 JSON으로 저장할 때 사용
import os  # 환경변수(API 키)와 파일 경로를 다룰 때 사용
import sys  # 프로그램 종료(sys.exit)에 사용
from pathlib import Path  # 폴더/파일 경로를 다루기 쉽게 해주는 도구
import openai
import matplotlib.pyplot as plt  # 컬러 팔레트를 이미지로 그릴 때 사용
import matplotlib.patches as patches  # 네모 박스(사각형)를 그릴 때 사용

# ---------------------------------------------------------------------------
# 1) .env 파일 확인 후 환경변수로 넣기
#    (어떤 키 이름을 쓸지는 여기서 정하지 않는다. 팀원이 각자 os.environ에서 꺼낸다)
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

    pair_count = 0  # KEY=VALUE 로 인정한 줄 개수

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            # 빈 줄, 주석(# ...) 은 키가 아니므로 건너뛴다
            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            # "값" 또는 '값' 이면 따옴표 제거
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]

            # 이름과 값이 둘 다 있어야 KEY=VALUE 한 줄로 센다
            if not key or not value:
                continue

            pair_count += 1

            # 터미널에 이미 같은 이름이 있으면 덮어쓰지 않는다
            if key not in os.environ:
                os.environ[key] = value

    return pair_count


def get_api_key():
    """
    .env 가 있는지, 그 안에 KEY=값 줄이 최소 하나 있는지만 확인합니다.
    특정 키 이름(OPENAI_API_KEY 등)은 검사하지 않습니다.

    실제 키는 각 팀원 함수에서 예: os.environ.get("내가_쓰는_이름") 으로 가져가면 됩니다.
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
REQUIRED_BRIEF_FIELDS = ("industry", "target", "keywords")  # 반드시 있어야 하는 키
OPTIONAL_BRIEF_FIELDS = ("tone", "competitors", "notes")  # 없어도 되는 키


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
        output_dir = "./output"  # 기본값

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

    # 필수 필드가 모두 있는지 확인
    missing = [field for field in REQUIRED_BRIEF_FIELDS if not brief.get(field)]
    if missing:
        print("브리프에 필수 필드가 없습니다:", ", ".join(missing))
        print("필수: industry, target, keywords")
        print("선택: tone, competitors, notes")
        sys.exit(1)

    return brief


# ---------------------------------------------------------------------------
# 3) 팀원 공통: API 호출을 안전하게 감싸는 함수
#    (네이밍/슬로건/스토리/컬러/로고 담당이 각자 함수 안에서 그대로 복사해 쓰면 됨)
# ---------------------------------------------------------------------------
# 함수 이름만으로도 "어느 단계인지"를 추정하기 위한 표
# (step_name을 직접 넘기면 이 표보다 그게 우선한다)
_STEP_NAME_BY_FUNC = {
    "generate_naming": "네이밍",
    "generate_slogan": "슬로건",
    "generate_story": "스토리",
    "generate_color_palette": "컬러",
    "generate_logo": "로고",
}


def _looks_like_api_key_error(error):
    """
    OpenAI / Anthropic / HTTP 등 라이브러리가 달라도
    '키가 없거나 잘못됐다'는 신호를 최대한 같은 방식으로 알아챈다.

    라이브러리를 import하지 않고, 에러 객체에 있는 정보만 본다.
    (팀원이 openai를 쓰든 requests를 쓰든 이 함수는 그대로 동작한다)
    """
    # HTTP 상태 코드가 있으면 401(인증 실패), 403(권한 없음)을 키 문제로 본다
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(error, "status", None)
    if status in (401, 403):
        return True

    # OpenAI 등은 error.code / error.type 에 invalid_api_key 같은 값을 넣는다
    code = str(getattr(error, "code", "") or getattr(error, "type", "")).lower()
    if "api_key" in code or "apikey" in code or code in ("invalid_api_key", "authentication_error"):
        return True

    # 클래스 이름: AuthenticationError, PermissionDeniedError, AuthError 등
    class_name = type(error).__name__.lower()
    if "auth" in class_name or "permission" in class_name:
        return True

    # 메시지 문구로 한 번 더 확인 (한국어/영어 모두)
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


def _guess_step_name(func, step_name):
    """단계 이름이 없으면 함수 이름에서 알아낸다."""
    if step_name:
        return step_name

    func_name = getattr(func, "__name__", "") or ""
    if func_name in _STEP_NAME_BY_FUNC:
        return _STEP_NAME_BY_FUNC[func_name]

    # generate_naming → naming 처럼 접두어만 떼서 보여 준다
    if func_name.startswith("generate_"):
        return func_name[len("generate_"):]

    return func_name or "API"


def safe_api_call(func, *args, step_name=None, **kwargs):
    """
    어떤 함수든(API 호출, 내부 헬퍼 등) 받아서 실행하고,
    실패해도 프로그램이 죽지 않게 막아 주는 공통 함수.

    사용 예)
        # 1) 내 함수 + 위치 인자
        result = safe_api_call(generate_naming, brief)

        # 2) 단계 이름을 직접 지정 (권장 — 메시지에 그대로 나옴)
        result = safe_api_call(_ask_openai, brief, step_name="슬로건")

        # 3) 키워드 인자도 그대로 전달
        result = safe_api_call(
            client.chat.completions.create,
            model="gpt-5.4-mini",
            messages=messages,
            step_name="네이밍",
        )

    반환:
        성공 → func이 돌려준 값 그대로
        실패 → None  (호출한 쪽에서 if result is None: 으로 처리하면 됨)

    step_name은 키워드로만 넘긴다. 감싸는 함수의 인자 이름과 겹치지 않게
    항상 step_name=... 형태로 쓴다.
    """
    label = _guess_step_name(func, step_name)

    try:
        # *args: 순서대로 넘기는 값  (예: brief)
        # **kwargs: 이름 붙여 넘기는 값  (예: model="...")
        # step_name은 위 정의에서 이미 빠져 있으므로 func에는 전달되지 않는다
        return func(*args, **kwargs)
    except Exception as error:
        if _looks_like_api_key_error(error):
            print("API 키를 확인해주세요")
            return None

        print(f"{label} 단계에서 오류가 발생했습니다: {error}")
        return None


# ---------------------------------------------------------------------------
# 4) 5단계 생성 함수 (지금은 뼈대만 — 내용은 나중에 채움)
#    구현할 때: 실제 API 호출을 safe_api_call(...) 로 감싸면 된다
# ---------------------------------------------------------------------------
def generate_naming(brief):
    """
    입력: brief (딕셔너리) — industry, target, keywords 등
    출력: 브랜드명 후보 리스트
          각 항목은 이름과 의미를 담은 딕셔너리
          예) [{"name": "루나", "meaning": "달처럼 부드러운 이미지"}, ...]

    구현 예)
        return safe_api_call(_call_naming_api, brief, step_name="네이밍")
    """
    pass


def generate_slogan(brief):
    """
    입력: brief (딕셔너리)
    출력: 슬로건 문자열 리스트
          예) ["매일의 작은 빛", "당신 곁의 브랜드"]
    """
    pass


def generate_story(brief):
    """
    입력: brief (딕셔너리)
    출력: 브랜드 스토리 문자열 하나
    """
    client = openai.OpenAI()

    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[
            {"role": "system", "content": "당신은 감성적인 화장품 브랜드 스토리텔러입니다. 아토피로 인한 '생존'의 선택에서, 환경과 나를 위한 '선호'의 가치로 전환되는 스토리를 280자 내외로 따뜻하게 작성해주세요."},
            {"role": "user", "content": f"다음 기획안을 바탕으로 스토리를 써주세요:\n{brief}"}
        ]
    )
    return response.choices[0].message.content


def generate_color_palette(brief):
    """
    입력: brief (딕셔너리)
    출력: 컬러 팔레트 딕셔너리
    """
    # 우리가 팀에서 확정한 컬러 팔레트를 그대로 반환
    return {
        "main": "#87A96B",              # 세이지 그린
        "sub": ["#F5F5DC", "#A9D1E1"]   # 웜 베이지, 미스트 블루
    }


def save_color_palette_image(color_dict, output_dir):
    """
    입력:
      - color_dict: {"main": "#HEX", "sub": ["#HEX", "#HEX", ...]} 형태
      - output_dir: 이미지를 저장할 폴더 (문자열 또는 Path 둘 다 가능)
    출력: 저장된 이미지 파일 경로(문자열)

    메인 컬러 1개 + 서브 컬러 여러 개를 가로로 나란히 놓인 네모 박스로
    그리고, 각 박스 아래에 HEX 코드를 텍스트로 표시해서 PNG로 저장한다.
    color_dict가 없거나(None) 형식이 이상하면 에러 메시지만 출력하고
    None을 반환한다 (프로그램이 멈추지 않게).
    """
    # color_dict가 아예 없거나(이전 단계 실패) 딕셔너리가 아니면 건너뛴다
    if not color_dict or not isinstance(color_dict, dict):
        print("컬러 팔레트 정보가 없어 이미지를 만들 수 없습니다.")
        return None

    main_color = color_dict.get("main")
    sub_colors = color_dict.get("sub", []) or []

    if not main_color:
        print("메인 컬러가 없어 이미지를 만들 수 없습니다.")
        return None

    # 메인 컬러 + 서브 컬러들을 한 리스트로 합치고, 어떤 게 메인인지 기억해둔다
    all_colors = [main_color] + list(sub_colors)

    # 박스 크기 설정: 메인 컬러 박스가 서브 컬러보다 살짝 더 크게
    box_width = 2.0
    main_box_height = 2.0
    sub_box_height = 1.5

    # 그림판(figure)과 좌표축(axes)을 하나 만든다
    # figsize: 그림 전체 크기 (가로, 세로) 인치 단위
    fig, ax = plt.subplots(figsize=(box_width * len(all_colors), 3))

    for i, hex_color in enumerate(all_colors):
        is_main = (i == 0)
        box_height = main_box_height if is_main else sub_box_height

        # 박스의 왼쪽 아래 좌표 (x, y)
        x = i * box_width
        y = 0

        # 사각형(Rectangle) 그리기: (왼쪽아래 좌표, 가로길이, 세로길이, 색)
        rect = patches.Rectangle(
            (x, y),
            box_width * 0.9,  # 박스 사이에 살짝 간격을 두기 위해 0.9배
            box_height,
            facecolor=hex_color,
            edgecolor="black",
            linewidth=1,
        )
        ax.add_patch(rect)

        # 박스 아래에 HEX 코드 텍스트 표시
        label = f"{hex_color}\n(Main)" if is_main else hex_color
        ax.text(
            x + (box_width * 0.9) / 2,   # 박스 가로 중앙
            -0.3,                         # 박스 아래쪽
            label,
            ha="center",
            va="top",
            fontsize=10,
        )

    # 좌표축 범위를 박스들이 다 보이게 설정
    ax.set_xlim(-0.2, box_width * len(all_colors))
    ax.set_ylim(-1, main_box_height + 0.5)

    # 눈금, 테두리선은 필요 없으니 다 꺼서 깔끔하게 만든다
    ax.axis("off")
    ax.set_title("Brand Color Palette", fontsize=14, pad=15)

    # 저장할 폴더가 없으면 만든다
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    image_path = output_path / "color_palette.png"

    # bbox_inches="tight": 여백을 딱 맞게 잘라서 저장
    fig.savefig(image_path, bbox_inches="tight", dpi=150)
    plt.close(fig)  # 메모리에 그림이 계속 쌓이지 않게 닫아준다

    print(f"컬러 팔레트 이미지가 {image_path}에 저장되었습니다")
    return str(image_path)


def generate_logo(brief, naming_result, color_result):
    """
    입력:
      - brief: 브리프 딕셔너리
      - naming_result: generate_naming()이 만든 이름 후보 리스트
      - color_result: generate_color_palette()가 만든 색상 딕셔너리
    출력: 저장된 로고 이미지 파일 경로 리스트
          예) ["./output/logo_1.png", "./output/logo_2.png"]
    """
    pass


# ---------------------------------------------------------------------------
# 5) 한 단계를 안전하게 실행 (실패해도 프로그램은 계속)
# ---------------------------------------------------------------------------
def run_step(step_number, total_steps, title, func, *args):
    """
    진행 메시지를 출력한 뒤 함수를 호출합니다.
    에러가 나도 메시지를 찍고 None을 반환해서, 다음 단계로 넘어가게 합니다.

    *args: 그 단계 함수에 넘겨줄 인자들
           (예: brief, 또는 brief + naming_result + color_result)
    """
    print(f"[{step_number}/{total_steps}] {title} 생성 중...")

    try:
        result = func(*args)
        return result
    except Exception as error:
        # Exception: 거의 모든 실행 중 오류를 잡는다
        print(f"  → {title} 단계에서 오류가 났습니다: {error}")
        print("  → 이 단계는 건너뛰고 다음 단계로 진행합니다.")
        return None


# ---------------------------------------------------------------------------
# 6) 결과를 JSON 파일로 저장
# ---------------------------------------------------------------------------
def save_result(output_dir, result_dict):
    """
    5단계 결과를 모은 딕셔너리(result_dict)를
    output_dir/brand_result.json 파일로 저장한다.

    - output_dir이 문자열("./output")이든 Path 객체든 모두 받는다
    - 폴더가 없으면 만든다 (중간 폴더까지 포함)
    - 한글이 유니코드 이스케이프(역슬래시 u + 숫자)로 깨지지 않게
      ensure_ascii=False 로 저장한다
    """
    # 문자열로 들어와도 Path로 바꿔서 폴더/파일 다루기 쉽게 만든다
    output_path = Path(output_dir)

    # parents=True: output/하위 처럼 중간 폴더도 같이 생성
    # exist_ok=True: 이미 폴더가 있어도 에러 내지 않음
    output_path.mkdir(parents=True, exist_ok=True)

    result_file = output_path / "brand_result.json"

    # encoding="utf-8": 한글 파일로 저장
    with result_file.open("w", encoding="utf-8") as f:
        # ensure_ascii=False → 한글을 그대로 기록
        # indent=2 → 들여써서 사람이 읽기 쉽게
        json.dump(result_dict, f, ensure_ascii=False, indent=2)

    print(f"결과가 {result_file}에 저장되었습니다")
    return str(result_file)


# ---------------------------------------------------------------------------
# 7) 프로그램 시작점 (여기부터 실행됨)
# ---------------------------------------------------------------------------
def main():
    # (1) .env를 환경변수로 올린다. 키 이름은 팀원이 각자 os.environ에서 꺼낸다.
    get_api_key()

    # (2) 경로 입력 → JSON 읽기
    brief_path, output_dir = ask_paths()
    brief = load_brief(brief_path)

    print()
    print("브리프를 읽었습니다. 5단계를 시작합니다.")
    print()

    # (3) 5단계를 순서대로 실행. 실패해도 다음으로 진행
    naming_result = run_step(1, 5, "브랜드 네이밍", generate_naming, brief)
    slogan_result = run_step(2, 5, "슬로건", generate_slogan, brief)
    story_result = run_step(3, 5, "브랜드 스토리", generate_story, brief)
    color_result = run_step(4, 5, "컬러 팔레트", generate_color_palette, brief)

    # (3-1) 컬러 팔레트를 이미지(PNG)로 저장 — 실패해도 다음 단계로 진행
    color_palette_image_path = run_step(
        "4b", 5, "컬러 팔레트 이미지 저장", save_color_palette_image, color_result, output_dir
    )

    logo_result = run_step(
        5,
        5,
        "로고",
        generate_logo,
        brief,
        naming_result,
        color_result,
    )

    # (4) 모든 결과를 한 딕셔너리에 모은다
    results = {
        "brief": brief,  # 원본 브리프도 같이 남겨 두면 나중에 추적하기 쉽다
        "naming": naming_result,  # 이름+의미 리스트 (실패 시 None)
        "slogan": slogan_result,  # 슬로건 리스트
        "story": story_result,  # 스토리 문자열
        "color_palette": color_result,  # {"main": "#HEX", "sub": ["#HEX", "#HEX"]}
        "color_palette_image": color_palette_image_path,  # 저장된 팔레트 이미지 경로
        "logo_paths": logo_result,  # 저장된 이미지 경로 리스트
    }

    # (5) JSON으로 저장 (폴더가 없으면 save_result 안에서 생성)
    save_result(output_dir, results)


# 이 파일을 직접 실행했을 때만 main()을 호출한다
# (다른 파일이 이 파일을 import 할 때는 자동 실행되지 않음)
if __name__ == "__main__":
    main()