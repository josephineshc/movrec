"""
LLM 추천 어시스턴트 + 감정 다양화 — 추천 로직 (자유 추천 버전)

LLM은 데이터셋에 묶이지 않고 2000년 이후 영화를 자유롭게 추천한다.
추천할 때 각 영화의 8가지 감정 점수(Plutchik, 0~1)도 함께 매긴다.
TMDB로 실제 존재하는 영화인지 확인하고 포스터·줄거리·장르를 가져온다.

세 조건 (참가자당 Gemini 호출 1번)
  baseline   : 후보 30편을 순위대로 추천받음 → 확인된 영화 중 상위 10편
  prompt_div : 다양화 지시를 추가해 12편 추천받음 → 확인된 영화 중 상위 10편
  emotion_div: baseline과 같은 30편 → Lansman et al. (2025) Table 2 알고리즘으로 10편
               (LLM 감정 점수 8차원, 맨해튼 거리)
세 조건 모두 최종 10편은 LLM 순위 순서로 보여줌.

환경변수: GEMINI_API_KEY, TMDB_API_KEY (v3 API 키 또는 v4 읽기 토큰)
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ───────── 설정 ─────────
GEN_MODEL = os.environ.get("GEN_MODEL", "gemini-3-flash-preview")  # Gemini 3 Flash
THINKING_LEVEL = os.environ.get("THINKING_LEVEL", "low")           # minimal/low/medium/high
MIN_YEAR = 2000
N_CANDIDATES = 30       # baseline·emotion_div 후보 수
N_PROMPT_DIV = 12       # prompt_div 요청 수 (TMDB에서 못 찾는 영화 대비 여유 2편)
MIN_POOL = 20           # 30편 요청 시 확인된 영화가 이보다 적으면 1번 더 요청 (무료 한도 아끼기)
N_SHOW = 10
EMOTIONS = ["joy", "trust", "fear", "surprise", "sadness", "disgust", "anger", "anticipation"]


def load_movies(path) -> pd.DataFrame:
    """선호 영화 5편 고르기용 데이터셋 (Lansman et al.)"""
    return pd.read_csv(path).set_index("id", drop=False)


def norm_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"^(the|a|an) ", "", t)
    return re.sub(r"[^a-z0-9]", "", t)


# ───────── Gemini ─────────
CAND_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "year": {"type": "integer"},
            "genres": {"type": "string"},
            "plot": {"type": "string"},
            "emotions": {
                "type": "object",
                "properties": {e: {"type": "number"} for e in EMOTIONS},
                "required": EMOTIONS,
            },
        },
        "required": ["title", "year", "genres", "plot", "emotions"],
    },
}


class Gemini:
    def __init__(self, api_key: str | None = None):
        from google import genai
        from google.genai import types
        self.types = types
        self.client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])

    def generate_json(self, prompt: str) -> list[dict]:
        res = self.client.models.generate_content(
            model=GEN_MODEL, contents=prompt,
            config=self.types.GenerateContentConfig(
                thinking_config=self.types.ThinkingConfig(thinking_level=THINKING_LEVEL),
                response_mime_type="application/json",
                response_json_schema=CAND_SCHEMA,
            ),
        )
        return json.loads(res.text)


PROMPT = """You are a movie recommendation assistant.

The user likes these movies:
{liked}

The user's request:
"{query}"

Recommend {n} real movies released in {min_year} or later that best satisfy the user's request \
and match their taste, ranked from most to least recommended. \
Do not include the movies the user already listed.{extra}

For each movie give: the exact English title, release year, genres, a one- or two-sentence plot summary, \
and how strongly the movie evokes each of Plutchik's eight basic emotions in viewers \
(joy, trust, fear, surprise, sadness, disgust, anger, anticipation), each as a number from 0 (not at all) to 1 (very strongly)."""

DIVERSIFY_EXTRA = ("\nFollow the user's request, but compose the list of movies that each evoke "
                   "a different mood and emotion.")


def liked_text(m: dict) -> str:
    return f"- {m['title']} ({m['year']}) | Genres: {m['genres']} | Plot: {m['plot']}"


def build_prompt(query: str, liked: list[dict], n: int, diversify: bool) -> str:
    return PROMPT.format(liked="\n".join(map(liked_text, liked)), query=query, n=n,
                         min_year=MIN_YEAR, extra=DIVERSIFY_EXTRA if diversify else "")


def clean_candidates(raw: list[dict], liked: list[dict]) -> list[dict]:
    """형식 확인, 2000년 이전·선호작·중복 제거, 감정 점수 0~1로 자르기"""
    liked_keys = {norm_title(m["title"]) for m in liked}
    seen, out = set(), []
    for c in raw:
        try:
            year = int(c["year"])
            emo = {e: float(np.clip(float(c["emotions"][e]), 0, 1)) for e in EMOTIONS}
        except (KeyError, TypeError, ValueError):
            continue
        key = norm_title(c.get("title", ""))
        if not key or year < MIN_YEAR or key in liked_keys or key in seen:
            continue
        seen.add(key)
        out.append({"title": str(c["title"]).strip(), "year": year, "genres": str(c.get("genres", "")),
                    "plot": str(c.get("plot", "")), "emotions": emo, "llm_rank": len(out) + 1})
    return out


# ───────── TMDB ─────────
class Tmdb:
    """실존 확인 + 포스터·줄거리·장르. 키가 없으면 확인을 건너뜀(포스터 없음)."""
    BASE = "https://api.themoviedb.org/3"
    IMG = "https://image.tmdb.org/t/p/w342"

    def __init__(self, key: str | None = None):
        import httpx
        self.key = key or os.environ.get("TMDB_API_KEY")
        headers, self.params = {}, {"language": "en-US"}
        if self.key and len(self.key) > 40:           # v4 읽기 토큰
            headers["Authorization"] = f"Bearer {self.key}"
        elif self.key:                                # v3 API 키
            self.params["api_key"] = self.key
        self.http = httpx.Client(base_url=self.BASE, headers=headers, timeout=10)
        self.genres = {}
        if self.key:
            r = self.http.get("/genre/movie/list", params=self.params)
            r.raise_for_status()
            self.genres = {g["id"]: g["name"] for g in r.json()["genres"]}

    def _search(self, title, year=None):
        p = {**self.params, "query": title, "include_adult": "false"}
        if year:
            p["primary_release_year"] = year
        r = self.http.get("/search/movie", params=p)
        r.raise_for_status()
        return r.json().get("results", [])

    def lookup(self, title: str, year: int) -> dict | None:
        res = self._search(title, year)
        if not res:                                   # 연도가 1년 어긋난 경우
            res = [m for m in self._search(title)
                   if m.get("release_date", "")[:4].isdigit() and abs(int(m["release_date"][:4]) - year) <= 1]
        if not res:
            return None
        m = res[0]
        return {
            "tmdb_id": m["id"], "tmdb_title": m["title"],
            "tmdb_year": int(m["release_date"][:4]) if m.get("release_date", "")[:4].isdigit() else year,
            "poster": self.IMG + m["poster_path"] if m.get("poster_path") else None,
            "overview": m.get("overview") or "",
            "tmdb_genres": ", ".join(self.genres.get(g, "") for g in m.get("genre_ids", []) if g in self.genres),
        }


def verify(cands: list[dict], tmdb, log: dict) -> list[dict]:
    """TMDB에서 찾은 영화만 남기고, 화면용 정보(제목·연도·장르·줄거리·포스터)를 붙임"""
    if not getattr(tmdb, "key", None):
        for c in cands:
            c.update(key=f"llm:{norm_title(c['title'])}:{c['year']}", poster=None)
        return cands
    with ThreadPoolExecutor(8) as ex:
        found = list(ex.map(lambda c: tmdb.lookup(c["title"], c["year"]), cands))
    out, ids = [], set()
    for c, f in zip(cands, found):
        if f is None or f["tmdb_year"] < MIN_YEAR or f["tmdb_id"] in ids:
            log.setdefault("not_found", []).append(f"{c['title']} ({c['year']})")
            continue
        ids.add(f["tmdb_id"])
        c.update(key=f"tmdb:{f['tmdb_id']}", tmdb_id=f["tmdb_id"], title=f["tmdb_title"], year=f["tmdb_year"],
                 poster=f["poster"], plot=f["overview"] or c["plot"], genres=f["tmdb_genres"] or c["genres"])
        out.append(c)
    return out


def get_candidates(llm, tmdb, query, liked, n, need, diversify, log) -> list[dict]:
    """LLM 추천 → 정리 → TMDB 확인. need편이 안 되면 1번 더 요청해 합침."""
    prompt = build_prompt(query, liked, n, diversify)
    log["prompt"] = prompt
    pool: list[dict] = []
    for attempt in range(2):
        raw = llm.generate_json(prompt)
        log.setdefault("raw_responses", []).append(raw)
        known = {c["key"] for c in pool}
        new = [c for c in verify(clean_candidates(raw, liked), tmdb, log) if c["key"] not in known]
        pool += new
        if len(pool) >= need:
            break
    for i, c in enumerate(pool):                     # 최종 LLM 순위 (첫 응답 순서 우선)
        c["llm_rank"] = i + 1
    if len(pool) < N_SHOW:
        raise RuntimeError(f"추천 영화가 {len(pool)}편밖에 확인되지 않음")
    return pool


# ───────── 감정 다양화 (Lansman et al. 2025, Table 2) ─────────
def emo_matrix(ms: list[dict]) -> np.ndarray:
    return np.array([[m["emotions"][e] for e in EMOTIONS] for m in ms], dtype=float)


def diversify(cands: list[dict], h: int = N_SHOW) -> list[dict]:
    """
    1) 후보 감정 벡터의 중심(평균)에 가장 가까운 영화를 첫 번째로
    2) 이미 고른 영화들과의 맨해튼 거리 합이 가장 큰 영화를 하나씩 추가
    """
    Q = emo_matrix(cands)
    remaining = list(range(len(cands)))
    centroid = Q.mean(axis=0)
    first = min(remaining, key=lambda i: np.abs(Q[i] - centroid).sum())
    chosen = [first]
    remaining.remove(first)
    while len(chosen) < h and remaining:
        nxt = max(remaining, key=lambda i: np.abs(Q[i] - Q[chosen]).sum())
        chosen.append(nxt)
        remaining.remove(nxt)
    return [cands[i] for i in chosen]


# ───────── 조건별 추천 ─────────
CONDITIONS = ("baseline", "prompt_div", "emotion_div")


@dataclass
class Result:
    condition: str
    shown: list[dict]                       # 화면에 보여줄 10편 (LLM 순위 순)
    log: dict = field(default_factory=dict)


def recommend(condition: str, query: str, liked: list[dict], llm, tmdb) -> Result:
    """liked: 선호 영화 5편 (title, year, genres, plot)"""
    assert condition in CONDITIONS and len(liked) == 5
    log: dict = {"model": GEN_MODEL, "thinking_level": THINKING_LEVEL}
    t0 = time.time()
    if condition == "prompt_div":
        cands = get_candidates(llm, tmdb, query, liked, N_PROMPT_DIV, N_SHOW, True, log)
        shown = cands[:N_SHOW]
    else:
        cands = get_candidates(llm, tmdb, query, liked, N_CANDIDATES, MIN_POOL, False, log)
        if condition == "baseline":
            shown = cands[:N_SHOW]
        else:
            picked = {c["key"] for c in diversify(cands)}
            shown = [c for c in cands if c["key"] in picked]     # LLM 순위 순으로 재정렬
    log["candidates"] = cands
    log["seconds"] = round(time.time() - t0, 2)
    return Result(condition, shown, log)


# ───────── 조작 점검 지표 (Lansman et al. Table 5) ─────────
def aesr(ms):
    """Average Emotion Score Range: 감정별 (최댓값-최솟값)의 평균"""
    Q = emo_matrix(ms)
    return float((Q.max(0) - Q.min(0)).mean())


def aeed(ms):
    """Average Emotions Euclidean Distance: 모든 영화 쌍의 유클리드 거리 평균"""
    Q = emo_matrix(ms)
    return float(np.mean([np.linalg.norm(Q[i] - Q[j]) for i in range(len(Q)) for j in range(i + 1, len(Q))]))


def aghd(ms, n_genres: int = 19):
    """Average Genre Hamming Distance: 장르 집합의 쌍별 대칭차 크기 / 전체 장르 수(TMDB 19개)"""
    G = [{g.strip() for g in str(m["genres"]).split(",") if g.strip()} for m in ms]
    return float(np.mean([len(G[i] ^ G[j]) / n_genres for i in range(len(G)) for j in range(i + 1, len(G))]))
