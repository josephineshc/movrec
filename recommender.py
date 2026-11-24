"""
추천 로직 — 세 조건

  baseline   (Gemini)   : 선호 영화 5편 + 질의로 Gemini가 2000년 이후 영화를 자유 추천 → 상위 10편
  prompt_div (Gemini)   : 위와 같고 "서로 다른 분위기와 감정" 지시 추가 → 상위 10편
  emotion_div(원 논문)  : Lansman et al. (2025) 그대로. Gemini·질의 사용 안 함.
                          ALS 평점 모델이 선호 영화 5편으로 매긴 상위 200편(2000–2020 데이터셋)
                          → 리뷰 기반 감정 시그니처(원점수 8차원, 맨해튼 거리)로 Table 2 알고리즘 → 10편

세 조건 모두 화면에는 TMDB 포스터·줄거리·장르로 똑같이 보여주고, 원래 순위(LLM 또는 ALS) 순서로 정렬.
조작 점검(AESR 등)은 데이터셋 감정 시그니처로 계산 — Gemini 추천 영화는 데이터셋에 있는 것만 계산됨.

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
N_SHOW = 10
N_REQUEST = 12          # Gemini에 요청하는 수 (TMDB에서 못 찾는 영화 대비 여유 2편)
N_ALS_TOP = 200         # 원 논문: ALS 상위 200편에서 다양화
EMOTIONS = ["joy", "trust", "fear", "surprise", "sadness", "disgust", "anger", "anticipation"]


def load_movies(path) -> pd.DataFrame:
    """Lansman et al. 데이터셋 (선호 영화 고르기, ALS, 감정 시그니처)"""
    return pd.read_csv(path).set_index("id", drop=False)


def norm_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"^(the|a|an) ", "", t)
    return re.sub(r"[^a-z0-9]", "", t)


def signature(movies: pd.DataFrame, imdb_id: str | None) -> dict | None:
    if imdb_id and imdb_id in movies.index:
        return {e: float(movies.at[imdb_id, e]) for e in EMOTIONS}
    return None


# ───────── Gemini ─────────
CAND_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"title": {"type": "string"}, "year": {"type": "integer"}},
        "required": ["title", "year"],
    },
}


class Gemini:
    def __init__(self, api_key: str | None = None):
        from google import genai
        from google.genai import types
        self.types = types
        # preview 모델은 v1beta에서만 제공 (최신 라이브러리 기본값은 v1)
        self.client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"],
                                   http_options=types.HttpOptions(api_version="v1beta"))

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
For each movie give the exact English title and the release year."""

DIVERSIFY_EXTRA = ("\nFollow the user's request, but compose the list of movies that each evoke "
                   "a different mood and emotion.")


def build_prompt(query: str, liked: list[dict], diversify: bool) -> str:
    lines = "\n".join(f"- {m['title']} ({m['year']}) | Genres: {m['genres']} | Plot: {m['plot']}" for m in liked)
    return PROMPT.format(liked=lines, query=query, n=N_REQUEST, min_year=MIN_YEAR,
                         extra=DIVERSIFY_EXTRA if diversify else "")


def clean_candidates(raw: list[dict], liked: list[dict]) -> list[dict]:
    """형식 확인, 2000년 이전·선호작·중복 제거"""
    liked_keys = {norm_title(m["title"]) for m in liked}
    seen, out = set(), []
    for c in raw:
        try:
            year, key = int(c["year"]), norm_title(c["title"])
        except (KeyError, TypeError, ValueError):
            continue
        if not key or year < MIN_YEAR or key in liked_keys or key in seen:
            continue
        seen.add(key)
        out.append({"title": str(c["title"]).strip(), "year": year})
    return out


# ───────── TMDB ─────────
class Tmdb:
    """실존 확인 + 포스터·줄거리·장르 + IMDb ID"""
    BASE = "https://api.themoviedb.org/3"
    IMG = "https://image.tmdb.org/t/p/w342"

    def __init__(self, key: str | None = None):
        import httpx
        self.key = key or os.environ.get("TMDB_API_KEY")
        if not self.key:
            raise RuntimeError("TMDB_API_KEY 환경변수가 필요해요")
        headers, self.params = {}, {"language": "en-US"}
        if len(self.key) > 40:                        # v4 읽기 토큰
            headers["Authorization"] = f"Bearer {self.key}"
        else:                                         # v3 API 키
            self.params["api_key"] = self.key
        self.http = httpx.Client(base_url=self.BASE, headers=headers, timeout=10)
        r = self.http.get("/genre/movie/list", params=self.params)
        r.raise_for_status()
        self.genres = {g["id"]: g["name"] for g in r.json()["genres"]}

    def _get(self, path, **params):
        r = self.http.get(path, params={**self.params, **params})
        r.raise_for_status()
        return r.json()

    def _card(self, m: dict) -> dict:
        y = m.get("release_date", "")[:4]
        return {"tmdb_id": m["id"], "title": m["title"], "year": int(y) if y.isdigit() else None,
                "poster": self.IMG + m["poster_path"] if m.get("poster_path") else None,
                "plot": m.get("overview") or "",
                "genres": ", ".join(self.genres[g] for g in m.get("genre_ids", []) if g in self.genres)}

    def search(self, title: str, year: int) -> dict | None:
        """Gemini 추천 영화 찾기 (연도 ±1 허용) + IMDb ID"""
        res = self._get("/search/movie", query=title, primary_release_year=year, include_adult="false")["results"]
        if not res:
            res = [m for m in self._get("/search/movie", query=title, include_adult="false")["results"]
                   if m.get("release_date", "")[:4].isdigit() and abs(int(m["release_date"][:4]) - year) <= 1]
        if not res:
            return None
        card = self._card(res[0])
        card["imdb_id"] = self._get(f"/movie/{card['tmdb_id']}/external_ids").get("imdb_id")
        return card

    def find_imdb(self, imdb_id: str) -> dict | None:
        """데이터셋 영화(IMDb ID) → TMDB 정보"""
        res = self._get(f"/find/{imdb_id}", external_source="imdb_id")["movie_results"]
        if not res:
            return None
        card = self._card(res[0])
        card["imdb_id"] = imdb_id
        return card


def pmap(fn, xs):
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(fn, xs))


# ───────── ALS (원 논문 평점 모델) ─────────
class ALS:
    """train_als.py 로 만든 als_model.npz 를 읽어 새 사용자 fold-in"""

    def __init__(self, path):
        z = np.load(path)
        self.ids, self.Q, self.bi = list(z["ids"]), z["Q"], z["bi"]
        self.mu, self.reg = float(z["mu"]), float(z["reg"])
        self.pos = {m: i for i, m in enumerate(self.ids)}

    def top(self, liked_ids: list[str], n: int = N_ALS_TOP, liked_rating: float = 5.0) -> list[tuple[str, float]]:
        idx = [self.pos[m] for m in liked_ids if m in self.pos]
        if not idx:
            raise RuntimeError("선호 영화가 ALS 모델에 없음")
        X = np.hstack([np.ones((len(idx), 1)), self.Q[idx]])
        y = liked_rating - self.mu - self.bi[idx]
        sol = np.linalg.solve(X.T @ X + self.reg * len(idx) * np.eye(X.shape[1]), X.T @ y)
        scores = self.mu + self.bi + sol[0] + self.Q @ sol[1:]
        scores[idx] = -np.inf
        order = np.argsort(-scores)[:n]
        return [(self.ids[i], float(scores[i])) for i in order]


# ───────── 감정 다양화 (Lansman et al. 2025, Table 2) ─────────
def diversify(ids: list[str], movies: pd.DataFrame, h: int = N_SHOW) -> list[str]:
    """
    1) 후보 감정 시그니처의 중심(평균)에 가장 가까운 영화를 첫 번째로
    2) 이미 고른 영화들과의 맨해튼 거리 합이 가장 큰 영화를 하나씩 추가
    """
    Q = movies.loc[ids, EMOTIONS].to_numpy(float)
    remaining = list(range(len(ids)))
    centroid = Q.mean(axis=0)
    first = min(remaining, key=lambda i: np.abs(Q[i] - centroid).sum())
    chosen = [first]
    remaining.remove(first)
    while len(chosen) < h and remaining:
        nxt = max(remaining, key=lambda i: np.abs(Q[i] - Q[chosen]).sum())
        chosen.append(nxt)
        remaining.remove(nxt)
    return [ids[i] for i in chosen]


# ───────── 조건별 추천 ─────────
CONDITIONS = ("baseline", "prompt_div", "emotion_div")


@dataclass
class Result:
    condition: str
    shown: list[dict]                       # 화면에 보여줄 10편 (원래 순위 순)
    log: dict = field(default_factory=dict)


def gemini_recs(query, liked, diversify_prompt, llm, tmdb, movies, log) -> list[dict]:
    prompt = build_prompt(query, liked, diversify_prompt)
    log.update(model=GEN_MODEL, thinking_level=THINKING_LEVEL, prompt=prompt)
    pool: list[dict] = []
    for attempt in range(2):                         # 10편이 안 되면 1번 더 요청
        raw = llm.generate_json(prompt)
        log.setdefault("raw_responses", []).append(raw)
        cands = clean_candidates(raw, liked)
        for c, f in zip(cands, pmap(lambda c: tmdb.search(c["title"], c["year"]), cands)):
            if f is None or (f["year"] or 0) < MIN_YEAR or any(p["tmdb_id"] == f["tmdb_id"] for p in pool) \
                    or f.get("imdb_id") in {m.get("imdb_id") for m in liked}:
                log.setdefault("not_found", []).append(f"{c['title']} ({c['year']})")
                continue
            pool.append({**f, "llm_title": c["title"], "llm_year": c["year"]})
        if len(pool) >= N_SHOW:
            break
    if len(pool) < N_SHOW:
        raise RuntimeError(f"추천 영화가 {len(pool)}편밖에 확인되지 않음")
    shown = pool[:N_SHOW]
    for i, c in enumerate(shown):
        c.update(key=f"tmdb:{c['tmdb_id']}", source="gemini", rank=i + 1,
                 signature=signature(movies, c.get("imdb_id")))
    return shown


def emotion_recs(liked_ids, als, tmdb, movies, log) -> list[dict]:
    top = als.top(liked_ids)
    log.update(model="ALS", als_top=[m for m, _ in top])
    rank = {m: i + 1 for i, (m, _) in enumerate(top)}
    picked = diversify([m for m, _ in top], movies)
    picked.sort(key=rank.get)                        # ALS 순위 순으로 재정렬
    log["diversified"] = picked
    shown = []
    for mid, f in zip(picked, pmap(tmdb.find_imdb, picked)):
        m = movies.loc[mid]
        if f is None:                                # TMDB에 없으면 데이터셋 정보로 대신
            log.setdefault("not_found", []).append(mid)
            f = {"tmdb_id": None, "title": m["title"], "year": int(m["year"]), "poster": None,
                 "plot": m["plot"], "genres": m["genres"], "imdb_id": mid}
        shown.append({**f, "key": f"imdb:{mid}", "source": "als", "rank": rank[mid],
                      "signature": signature(movies, mid)})
    return shown


def recommend(condition, query, liked_ids, movies, llm, tmdb, als) -> Result:
    assert condition in CONDITIONS and len(liked_ids) == 5
    liked = [{"title": movies.at[m, "title"], "year": int(movies.at[m, "year"]), "genres": movies.at[m, "genres"],
              "plot": movies.at[m, "plot"], "imdb_id": m} for m in liked_ids]
    log: dict = {}
    t0 = time.time()
    if condition == "emotion_div":
        shown = emotion_recs(liked_ids, als, tmdb, movies, log)
    else:
        shown = gemini_recs(query, liked, condition == "prompt_div", llm, tmdb, movies, log)
    log["seconds"] = round(time.time() - t0, 2)
    return Result(condition, shown, log)


# ───────── 조작 점검 지표 (Lansman et al. Table 5, 데이터셋 감정 시그니처) ─────────
def _sigs(ms):
    S = [m["signature"] for m in ms if m.get("signature")]
    return np.array([[s[e] for e in EMOTIONS] for s in S], dtype=float)


def coverage(ms):
    """감정 시그니처가 있는(데이터셋에 있는) 영화 수"""
    return len(_sigs(ms))


def aesr(ms):
    Q = _sigs(ms)
    return float((Q.max(0) - Q.min(0)).mean()) if len(Q) >= 2 else None


def aeed(ms):
    Q = _sigs(ms)
    if len(Q) < 2:
        return None
    return float(np.mean([np.linalg.norm(Q[i] - Q[j]) for i in range(len(Q)) for j in range(i + 1, len(Q))]))


def aghd(ms, n_genres: int = 19):
    """장르 집합 쌍별 대칭차 크기 / 전체 장르 수(TMDB 19개) — 10편 모두 계산"""
    G = [{g.strip() for g in str(m["genres"]).split(",") if g.strip()} for m in ms]
    return float(np.mean([len(G[i] ^ G[j]) / n_genres for i in range(len(G)) for j in range(i + 1, len(G))]))
