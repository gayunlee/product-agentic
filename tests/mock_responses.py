"""
Mock API 응답 데이터. 실제 dev 환경에서 가져온 응답 구조를 기반으로 작성.
"""

MASTER_GROUPS = {
    "masterGroups": [
        {"id": "group_001", "name": "테스트 마스터", "masterCount": 1},
        {"id": "group_002", "name": "에이전트 테스트", "masterCount": 0},
    ]
}

MASTER_GROUPS_EMPTY = {"masterGroups": []}

SEARCH_MASTERS_FOUND = [
    {
        "id": "655bfe94c7dacf9f1db4ceaf",
        "cmsId": "136",
        "name": "테스트 마스터",
        "createdAt": "2026-03-17 09:00",
        "publicType": "PUBLIC",
        "masterGroupId": "group_001",
        "masterGroupName": "테스트 마스터",
    }
]

SEARCH_MASTERS_EMPTY = []

SERIES_LIST_FOUND = {
    "masters": [
        {
            "_id": "655bfe94c7dacf9f1db4ceaf",
            "name": "테스트 마스터",
            "series": [
                {"_id": "series_001", "title": "투자 기초 시리즈"},
                {"_id": "series_002", "title": "경제 분석 시리즈"},
            ],
        }
    ]
}

SERIES_LIST_EMPTY = {"masters": [{"_id": "655bfe94c7dacf9f1db4ceaf", "name": "테스트 마스터", "series": []}]}

CREATE_SERIES_SUCCESS = {"content": {"id": "series_new_001", "cmsId": "291"}}

CREATE_MASTER_GROUP_SUCCESS = {"success": True, "status": 201}

PRODUCT_PAGE_LIST_EMPTY = []

PRODUCT_PAGE_LIST_FOUND = [
    {
        "id": "page_001",
        "title": "테스트 구독 상품",
        "startAt": "1970.01.01",
        "endAt": "9999.12.31",
        "isAlwaysPublic": True,
        "applyStartAt": "1970-01-01",
        "applyEndAt": "9999-12-31",
        "isAlwaysApply": True,
        "status": "INACTIVE",
        "code": 197,
        "createdAt": "2026.03.17",
        "isDeletable": True,
    }
]

CREATE_PRODUCT_PAGE_SUCCESS = {"success": True, "status": 201}

CREATE_PRODUCT_SUCCESS = {"id": 12345}

UPDATE_PRODUCT_DISPLAY_SUCCESS = {"success": True, "status": 200}

UPDATE_PRODUCT_SEQUENCE_SUCCESS = {"success": True, "status": 200}

UPDATE_PRODUCT_PAGE_STATUS_SUCCESS = {"success": True, "status": 200}

UPDATE_MAIN_PRODUCT_SETTING_SUCCESS = {"success": True, "status": 200}

PRODUCT_PAGE_DETAIL = {
    "id": "page_001",
    "masterId": "136",
    "title": "테스트 구독 상품",
    "status": "INACTIVE",
    "type": "SUBSCRIPTION",
    "code": 197,
    "isAlwaysPublic": True,
    "isChangeable": True,
    "mainContents": [{"type": "IMAGE", "contentUrl": "https://placehold.co/990x1100"}],
    "contents": [{"imageUrl": "https://placehold.co/990x1100", "sequence": 0}],
}

PRODUCT_LIST_BY_PAGE = [
    {
        "productId": "12345",
        "name": "월간 구독",
        "price": 29900,
        "type": "SUBSCRIPTION",
        "paymentPeriod": "ONE_MONTH",
        "isDisplay": True,
        "viewSequence": 0,
    }
]
