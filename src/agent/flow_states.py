"""
Phase별 고정 응답(버튼, 모드, 스텝)을 정의합니다.

LLM은 텍스트만 생성하고, 버튼/모드/스텝은 이 모듈이 강제합니다.
"""

STEPS = ["마스터 확인", "시리즈 확인", "상품 페이지 생성", "상품 옵션 등록", "활성화", "검증"]

PHASE_TO_STEP = {
    "init": 1,
    "series": 2,
    "product_page": 3,
    "product_option": 4,
    "activation": 5,
    "verification": 6,
}


def get_step_meta(phase: str) -> dict:
    """phase에 해당하는 step 메타 반환."""
    step_num = PHASE_TO_STEP.get(phase, 1)
    return {
        "current": step_num,
        "total": 6,
        "label": STEPS[step_num - 1],
        "steps": STEPS,
    }


def get_phase_buttons(phase: str, collected: dict) -> list[dict]:
    """phase + collected_data 기반으로 고정 버튼 반환."""
    master_id = collected.get("master_cms_id", "")
    master_name = collected.get("master_name", "")
    page_id = collected.get("product_page_id", "")
    page_code = collected.get("product_page_code", "")

    if phase == "init":
        if not master_id:
            # 마스터 아직 미확인 → 목록 조회 버튼만
            return [
                {
                    "type": "navigate",
                    "label": "📋 마스터 목록 보기",
                    "url": "/official-club",
                    "variant": "secondary",
                    "description": "등록된 마스터 목록을 확인합니다.",
                },
            ]
        else:
            # 마스터 확인됨 → 버튼 없음 (자동으로 시리즈 확인 진행)
            return []

    elif phase == "series":
        series_ids = collected.get("series_ids", [])
        if series_ids:
            # 시리즈 있음 → 버튼 없음 (자동으로 다음 단계 안내)
            return []
        else:
            # 시리즈 없음 → 파트너센터 안내
            return [
                {
                    "type": "navigate",
                    "label": "📝 파트너센터에서 시리즈 생성",
                    "url": "/partner",
                    "variant": "primary",
                    "description": "좌측 앱 전환 아이콘에서 '파트너'를 클릭해주세요.",
                },
                {
                    "type": "confirm",
                    "label": "✅ 시리즈 생성 완료",
                    "variant": "primary",
                    "description": "시리즈 생성을 완료했으면 눌러주세요. 시리즈를 재확인합니다.",
                },
            ]

    elif phase == "product_page":
        if not page_id:
            # 페이지 생성 전
            return [
                {
                    "type": "navigate",
                    "label": "📄 상품 페이지 생성하러 가기",
                    "url": "/product/page/create",
                    "variant": "primary",
                    "description": f"관리자센터에서 직접 생성합니다. 마스터에서 '{master_name}'을 선택하고, 정보 설정과 이미지까지 등록해주세요.",
                },
                {
                    "type": "confirm",
                    "label": "✅ 상품 페이지 생성 완료",
                    "variant": "primary",
                    "description": "생성을 완료했으면 눌러주세요. 결과를 확인합니다.",
                },
            ]
        else:
            # 페이지 생성 완료 → 버튼 없음 (자동으로 다음 단계)
            return []

    elif phase == "product_option":
        product_ids = collected.get("product_ids", [])
        buttons = [
            {
                "type": "navigate",
                "label": "📦 상품 옵션 등록하러 가기",
                "url": f"/product/create?productPageId={page_id}&productType=SUBSCRIPTION&masterId={master_id}",
                "variant": "primary",
                "description": "상품명, 금액, 결제주기, 시리즈를 입력해주세요.",
            },
            {
                "type": "confirm",
                "label": "✅ 상품 옵션 등록 완료",
                "variant": "primary",
                "description": "옵션 등록을 완료했으면 눌러주세요. 등록된 옵션을 확인합니다.",
            },
        ]
        if product_ids:
            buttons.append({
                "type": "confirm",
                "label": "➕ 옵션 하나 더 등록",
                "variant": "secondary",
                "description": "추가 옵션을 등록합니다.",
            })
        return buttons

    elif phase == "activation":
        return [
            {
                "type": "action",
                "label": "🚀 활성화하기",
                "actionId": "activate",
                "variant": "primary",
                "description": "상품 노출, 순서, 페이지 공개, 메인 상품 설정을 한번에 처리합니다.",
            },
        ]

    elif phase == "verification":
        buttons = []
        if page_id:
            buttons.extend([
                {
                    "type": "navigate",
                    "label": "⚠️ 유의사항 등록",
                    "url": f"/product/page/{page_id}?tab=caution",
                    "variant": "secondary",
                    "description": "유의사항을 등록합니다.",
                },
            ])
        if page_code:
            buttons.append({
                "type": "navigate",
                "label": "🌐 고객 화면 확인",
                "url": f"https://dev.us-insight.com/products/group/{page_code}",
                "variant": "secondary",
                "description": "고객에게 보이는 화면을 확인합니다.",
            })
        return buttons

    return []


def get_phase_mode(phase: str) -> str:
    """phase에 해당하는 모드 반환."""
    mode_map = {
        "init": "guide",
        "series": "execute",
        "product_page": "guide",
        "product_option": "guide",
        "activation": "execute",
        "verification": "execute",
    }
    return mode_map.get(phase, "idle")


def get_phase_response(phase: str, collected: dict) -> dict:
    """phase별 고정 응답 반환. LLM 텍스트 위에 덮어씌울 버튼/모드/스텝."""
    return {
        "buttons": get_phase_buttons(phase, collected),
        "mode": get_phase_mode(phase),
        "step": get_step_meta(phase),
    }
