"""
사용자 경험 설문 — Lansman et al. (2025) Table 3 문항 (7점 척도, 전혀 그렇지 않다 ~ 매우 그렇다)
reverse=True 는 역문항 (분석 때 8 - 점수)
한국어 번역은 초안 — 번역·역번역 검토 필요
"""

CONSTRUCTS = {
    "PD": "체감 다양성",
    "PQ": "체감 추천 품질",
    "CS": "선택 만족도",
    "TDO": "트레이드오프 난이도",
    "CD": "선택 난이도",
    "PTC": "체감 취향 커버리지",
    "SS": "시스템 만족도",
}

# (코드, 구성개념, 역문항, 영어 원문, 한국어)
ITEMS = [
    ("PD1", "PD", True,  "All the recommended movies in the final list were similar to each other",
     "최종 추천 목록의 영화들은 모두 서로 비슷했다"),
    ("PD2", "PD", False, "None of the movies in the recommended list were alike",
     "추천 목록에 서로 비슷한 영화는 하나도 없었다"),
    ("PD3", "PD", True,  "Most recommended movies were from the same genre",
     "추천된 영화 대부분이 같은 장르였다"),
    ("PD4", "PD", False, "The recommended list of movies suits a broad set of tastes",
     "추천 목록은 폭넓은 취향에 맞는다"),
    ("PD5", "PD", False, "The recommended movies were from many different genres",
     "추천된 영화들은 여러 다양한 장르였다"),
    ("PD6", "PD", False, "The recommendations contained a lot of variety",
     "추천에는 다양한 영화가 많이 담겨 있었다"),

    ("PQ1", "PQ", False, "I liked the movies recommended by the movie recommender",
     "추천 시스템이 추천한 영화들이 마음에 들었다"),
    ("PQ2", "PQ", False, "I found the recommended movies appealing",
     "추천된 영화들이 끌렸다"),
    ("PQ3", "PQ", False, "The recommended movies fit my preferences",
     "추천된 영화들은 내 취향에 맞았다"),
    ("PQ4", "PQ", False, "The recommended movies were relevant",
     "추천된 영화들은 적절했다"),
    ("PQ5", "PQ", True,  "The system recommended too many bad movies",
     "시스템이 별로인 영화를 너무 많이 추천했다"),
    ("PQ6", "PQ", True,  "I didn't like any of the recommended movies",
     "추천된 영화 중 마음에 드는 것이 하나도 없었다"),

    ("CS1", "CS", False, "I like the movie I've chosen from the final recommendation list",
     "최종 추천 목록에서 내가 고른 영화가 마음에 든다"),
    ("CS2", "CS", False, "The chosen movie fits my preference",
     "내가 고른 영화는 내 취향에 맞는다"),
    ("CS3", "CS", False, "I would recommend my chosen movie to others/friends",
     "내가 고른 영화를 다른 사람이나 친구에게 추천하겠다"),
    ("CS4", "CS", False, "I was excited about my chosen movie",
     "내가 고른 영화가 기대된다"),
    ("CS5", "CS", False, "I think I chose the best movie from the recommended options",
     "추천된 영화 중 가장 좋은 영화를 고른 것 같다"),
    ("CS6", "CS", True,  "I know several recommended items that are better than the one I selected",
     "추천된 영화 중 내가 고른 것보다 나은 영화가 여러 편 있다"),
    ("CS7", "CS", True,  "I would rather watch a different movie from the one I selected",
     "내가 고른 영화보다 다른 영화를 보고 싶다"),

    ("TDO1", "TDO", False, "I had to put a lot of effort into comparing the different aspects of the recommended movies",
     "추천된 영화들의 여러 측면을 비교하는 데 많은 노력이 들었다"),
    ("TDO2", "TDO", False, "Comparing the different recommended movies was like comparing apples and oranges",
     "추천된 영화들을 비교하는 것은 전혀 다른 것끼리 비교하는 느낌이었다"),
    ("TDO3", "TDO", True,  "It was easy to compare the recommended movies with each other",
     "추천된 영화들을 서로 비교하기 쉬웠다"),
    ("TDO4", "TDO", False, "The recommended movies were so different that they were hard to compare",
     "추천된 영화들이 너무 달라서 비교하기 어려웠다"),

    ("CD1", "CD", False, "I was in doubt between several movies on the list",
     "목록의 여러 영화 사이에서 고민했다"),
    ("CD2", "CD", False, "I changed my mind several times before making a decision",
     "결정하기 전에 마음을 여러 번 바꿨다"),
    ("CD3", "CD", False, "The task of making a decision was overwhelming",
     "결정하는 일이 버겁게 느껴졌다"),
    ("CD4", "CD", True,  "It was easy to select a movie",
     "영화를 고르기 쉬웠다"),
    ("CD5", "CD", False, "Comparing the movies took a lot of effort",
     "영화들을 비교하는 데 많은 노력이 들었다"),

    ("PTC1", "PTC", False, "The movie recommender catered to all of my potential interests",
     "추천 시스템은 내가 관심을 가질 만한 것들을 모두 고려했다"),
    ("PTC2", "PTC", True,  "The movies that were recommended did NOT reflect my diverse taste in movies",
     "추천된 영화들은 나의 다양한 영화 취향을 반영하지 못했다"),
    ("PTC3", "PTC", True,  "The movie recommender seemed to target only a small subset of my interests",
     "추천 시스템은 내 관심사 중 일부만 겨냥한 것 같았다"),
    ("PTC4", "PTC", True,  "The movie recommender treated me as a one-dimensional person",
     "추천 시스템은 나를 단면적인 사람으로 취급했다"),
    ("PTC5", "PTC", False, "The lists of recommendations matched a diversity of my preferences",
     "추천 목록은 나의 다양한 선호에 맞았다"),
    ("PTC6", "PTC", False, "The recommended movies were a perfect fit for me on many different levels",
     "추천된 영화들은 여러 면에서 나에게 잘 맞았다"),
    ("PTC7", "PTC", True,  "The movie recommender seemed to stereotype me in a particular category of viewers",
     "추천 시스템은 나를 특정 유형의 관객으로 고정해서 본 것 같았다"),

    ("SS1", "SS", False, "Using the recommender system is a pleasant experience",
     "이 추천 시스템을 사용하는 것은 즐거운 경험이다"),
    ("SS2", "SS", False, "I would recommend the system to others",
     "이 시스템을 다른 사람에게 추천하겠다"),
    ("SS3", "SS", False, "I can find better movies using the recommender system",
     "이 추천 시스템을 쓰면 더 좋은 영화를 찾을 수 있다"),
    ("SS4", "SS", True,  "The system is useless",
     "이 시스템은 쓸모없다"),
    ("SS5", "SS", False, "The system makes me more aware of my choice options",
     "이 시스템 덕분에 내가 고를 수 있는 선택지를 더 잘 알게 된다"),
    ("SS6", "SS", False, "I make better choices with the system",
     "이 시스템을 쓰면 더 나은 선택을 한다"),
    ("SS7", "SS", True,  "The system has no real benefit for me",
     "이 시스템은 나에게 실질적인 도움이 되지 않는다"),
]

# 주의 집중 확인 문항 (분석에서 제외 기준으로 사용)
ATTENTION = ("ATT1", "ATT", False, "Please select 'Somewhat agree' for this item",
             "이 문항에는 '약간 그렇다'를 선택해 주세요")
ATTENTION_ANSWER = 5

SCALE_KO = ["전혀 그렇지 않다", "그렇지 않다", "약간 그렇지 않다", "보통이다",
            "약간 그렇다", "그렇다", "매우 그렇다"]

# ───────── 실제로 쓰는 문항 ─────────
# 번호 = 위 ITEMS 순서(1~42) + 주의 확인 문항(43)
KEEP_NUMBERS = [1, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 19, 21, 23, 26, 27, 28,
                31, 32, 33, 34, 36, 37, 38, 39, 40, 43]
_ALL = ITEMS + [ATTENTION]
SURVEY_ITEMS = [_ALL[n - 1] for n in KEEP_NUMBERS]          # 주의 확인 문항 포함
SCORED_ITEMS = [it for it in SURVEY_ITEMS if it[0] != ATTENTION[0]]
