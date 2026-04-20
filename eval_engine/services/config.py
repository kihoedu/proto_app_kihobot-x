DEFAULT_CRITERIA = {
    "subject": "논술 평가",
    "total_score": 100,
    "dimensions": {
        "logic": {
            "weight": 0.25,
            "max_score": 25,
            "description": "논리적 흐름, 논증 구조, 주장-근거 연결성",
            "rubric": {
                "excellent": "주장이 명확하고 근거가 논리적으로 연결됨. 반론 고려 있음.",
                "good": "논리 흐름은 있으나 일부 논증 약함.",
                "average": "주장은 있으나 근거가 불충분하거나 논리 비약 있음.",
                "poor": "논리 구조 불명확, 주장과 근거 연결 없음."
            }
        },
        "content": {
            "weight": 0.30,
            "max_score": 30,
            "description": "주제 이해도, 내용의 깊이와 풍부함",
            "rubric": {
                "excellent": "주제를 깊이 이해하고 다각도로 분석함.",
                "good": "주제 이해도 양호, 핵심 내용 포함.",
                "average": "기본 내용은 있으나 깊이 부족.",
                "poor": "주제 이해 부족 또는 내용 빈약."
            }
        },
        "expression": {
            "weight": 0.20,
            "max_score": 20,
            "description": "어휘 수준, 문장력, 맞춤법·문법",
            "rubric": {
                "excellent": "풍부한 어휘, 정확한 문법, 명확한 표현.",
                "good": "적절한 어휘 사용, 소수의 오류.",
                "average": "기본적 표현 가능하나 오류 다수.",
                "poor": "표현 미숙, 잦은 문법·맞춤법 오류."
            }
        },
        "fact_check": {
            "weight": 0.15,
            "max_score": 15,
            "description": "사실 정확성, 인용·출처 타당성",
            "rubric": {
                "excellent": "사실 오류 없음, 근거 신뢰성 높음.",
                "good": "대체로 정확, 경미한 오류.",
                "average": "일부 사실 오류 또는 근거 불명확.",
                "poor": "명백한 사실 오류 다수."
            }
        },
        "creativity": {
            "weight": 0.10,
            "max_score": 10,
            "description": "독창적 관점, 창의적 발상, 참신한 예시",
            "rubric": {
                "excellent": "독창적 시각, 참신한 예시, 창의적 전개.",
                "good": "일부 독창적 요소 있음.",
                "average": "전형적 접근, 독창성 부족.",
                "poor": "상투적 표현만 사용."
            }
        }
    },
    "grade_scale": {
        "A+": (95, 100),
        "A":  (90, 95),
        "B+": (85, 90),
        "B":  (80, 85),
        "C+": (75, 80),
        "C":  (70, 75),
        "D":  (60, 70),
        "F":  (0, 60)
    }
}

CONSISTENCY_THRESHOLDS = {
    "max_variance": 15.0,       # 점수 분산 허용 최대치
    "min_confidence": 0.6,      # 에이전트 최소 확신도
    "max_retries": 2            # 최대 재평가 횟수
}
