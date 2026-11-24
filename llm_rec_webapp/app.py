"""
실험 웹앱 서버

실행:
  pip install -r requirements.txt
  export GEMINI_API_KEY=...  TMDB_API_KEY=...
  uvicorn app:app --port 8000          # → http://localhost:8000

가짜 모드 (Gemini·TMDB 없이 화면 흐름만 시험):  MOCK=1 uvicorn app:app --port 8000

필요한 파일 (같은 폴더): movies.csv, posters/<id>.jpg  (선호 영화 5편 고르기용)
환경변수 (선택):
  DATA_DIR    응답 DB 저장 폴더 (호스팅 시 영구 볼륨 경로, 예: /data)
  ADMIN_TOKEN /admin/db, /admin/stats 비밀번호
  SURVEY_URL  구글 설문 미리 채우기 링크 ({pid} 자리에 참가자 번호)
"""
from __future__ import annotations

import json
import os
import random
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import recommender as R
from questionnaire import ATTENTION, ITEMS, SCALE_KO

BASE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "experiment.db"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")
SURVEY_URL = os.environ.get("SURVEY_URL")
MOCK = os.environ.get("MOCK") == "1"

movies = R.load_movies(BASE / "movies.csv")
_title_lc = movies["title"].str.lower()


# ───────── Gemini·TMDB (진짜 / 가짜) ─────────
class MockLLM:
    """화면 테스트용: 데이터셋에서 무작위 영화 + 무작위 감정 점수"""
    def generate_json(self, prompt):
        time.sleep(1.5)
        n = int(re.search(r"Recommend (\d+)", prompt).group(1))
        rng = random.Random(prompt)
        pick = movies[movies["year"] >= R.MIN_YEAR].sample(n, random_state=rng.randrange(10**6))
        return [{"title": m.title, "year": int(m.year), "genres": m.genres, "plot": m.plot,
                 "emotions": {e: round(rng.random(), 2) for e in R.EMOTIONS}} for m in pick.itertuples()]


class MockTmdb:
    key = "mock"

    def lookup(self, title, year):
        hit = movies[(_title_lc == title.lower()) & (movies["year"] == year)]
        if hit.empty:
            return None
        m = hit.iloc[0]
        return {"tmdb_id": int(m["id"][2:]), "tmdb_title": m["title"], "tmdb_year": int(m["year"]),
                "poster": f"/poster/{m['id']}.jpg", "overview": m["plot"], "tmdb_genres": m["genres"]}


if MOCK:
    llm, tmdb = MockLLM(), MockTmdb()
    print("⚠️  MOCK 모드: 추천 결과는 의미 없음")
else:
    llm, tmdb = R.Gemini(), R.Tmdb()
    if not tmdb.key:
        print("⚠️  TMDB_API_KEY 없음: 실존 확인·포스터 없이 진행")


# ───────── DB ─────────
_lock = threading.Lock()


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


with db() as con:
    con.execute("""CREATE TABLE IF NOT EXISTS participants (
        pid TEXT PRIMARY KEY, condition TEXT, created REAL, ext_id TEXT,
        liked TEXT, query TEXT, shown TEXT, rec_log TEXT, rec_seconds REAL,
        choice TEXT, choice_time REAL, ratings TEXT,
        survey_order TEXT, survey TEXT, finished REAL, code TEXT)""")


def update(pid, **fields):
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, db() as con:
        cur = con.execute(f"UPDATE participants SET {cols} WHERE pid=?", (*fields.values(), pid))
        if cur.rowcount == 0:
            raise HTTPException(404, "참가자를 찾을 수 없어요")


def get(pid):
    with db() as con:
        row = con.execute("SELECT * FROM participants WHERE pid=?", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, "참가자를 찾을 수 없어요")
    return row


def assign_condition(con) -> str:
    """조건별 인원이 가장 적은 쪽으로 (동률이면 무작위)"""
    counts = {c: 0 for c in R.CONDITIONS}
    for row in con.execute("SELECT condition, COUNT(*) n FROM participants GROUP BY condition"):
        counts[row["condition"]] = row["n"]
    least = min(counts.values())
    return random.choice([c for c, n in counts.items() if n == least])


def dataset_card(mid):
    m = movies.loc[mid]
    return {"id": mid, "title": m["title"], "year": int(m["year"]), "genres": m["genres"], "plot": m["plot"]}


def rec_card(c):
    """화면에 보내는 정보 (감정 점수·순위는 보내지 않음)"""
    return {"id": c["key"], "title": c["title"], "year": c["year"], "genres": c["genres"],
            "plot": c["plot"], "poster": c.get("poster")}


# ───────── API ─────────
app = FastAPI()


class StartIn(BaseModel):
    ext_id: str | None = None


@app.post("/api/start")
def start(body: StartIn):
    pid = secrets.token_hex(8)
    with _lock, db() as con:
        cond = assign_condition(con)
        con.execute("INSERT INTO participants (pid, condition, created, ext_id) VALUES (?,?,?,?)",
                    (pid, cond, time.time(), body.ext_id))
    return {"pid": pid}


@app.get("/api/search")
def search(q: str):
    q = q.strip().lower()
    if len(q) < 2:
        return []
    hit = movies[_title_lc.str.contains(q, regex=False)]
    hit = hit.assign(_starts=~_title_lc[hit.index].str.startswith(q)).sort_values(["_starts", "year"])
    return [dataset_card(m) for m in hit.index[:20]]


class RecIn(BaseModel):
    pid: str
    liked: list[str]
    query: str


_busy: set[str] = set()


@app.post("/api/recommend")
def recommend(body: RecIn):
    row = get(body.pid)
    if row["shown"]:                                  # 새로고침해도 같은 결과
        return {"movies": [rec_card(c) for c in json.loads(row["shown"])]}
    if len(set(body.liked)) != 5 or any(m not in movies.index for m in body.liked):
        raise HTTPException(400, "좋아하는 영화 5편을 골라 주세요")
    if len(body.query.strip()) < 5:
        raise HTTPException(400, "요청을 조금 더 자세히 적어 주세요")
    if body.pid in _busy:                             # 중복 클릭으로 API 두 번 쓰는 것 방지
        raise HTTPException(429, "추천을 만드는 중이에요. 잠시만 기다려 주세요")
    _busy.add(body.pid)
    try:
        liked = [dataset_card(m) for m in body.liked]
        res = R.recommend(row["condition"], body.query.strip(), liked, llm, tmdb)
    except Exception as e:
        print("추천 실패:", body.pid, repr(e))
        raise HTTPException(503, "추천을 만들지 못했어요. 잠시 후 다시 시도해 주세요")
    finally:
        _busy.discard(body.pid)
    update(body.pid, liked=json.dumps(body.liked), query=body.query.strip(),
           shown=json.dumps(res.shown, ensure_ascii=False), rec_log=json.dumps(res.log, ensure_ascii=False),
           rec_seconds=res.log["seconds"])
    return {"movies": [rec_card(c) for c in res.shown]}


def shown_keys(row):
    return [c["key"] for c in json.loads(row["shown"] or "[]")]


class ChoiceIn(BaseModel):
    pid: str
    movie_id: str


@app.post("/api/choice")
def choice(body: ChoiceIn):
    row = get(body.pid)
    if body.movie_id not in shown_keys(row):
        raise HTTPException(400, "추천 목록에 없는 영화예요")
    update(body.pid, choice=body.movie_id, choice_time=time.time())
    return {"ok": True}


class Rating(BaseModel):
    id: str
    seen: bool
    like: int          # 1-5
    fit: bool          # 내 요청에 맞는지


class RatingsIn(BaseModel):
    pid: str
    ratings: list[Rating]


@app.post("/api/ratings")
def ratings(body: RatingsIn):
    row = get(body.pid)
    if sorted(r.id for r in body.ratings) != sorted(shown_keys(row)) or any(not 1 <= r.like <= 5 for r in body.ratings):
        raise HTTPException(400, "모든 영화에 응답해 주세요")
    update(body.pid, ratings=json.dumps([r.model_dump() for r in body.ratings]))
    if SURVEY_URL:                       # 설문은 구글 설문지에서 → 웹앱 과제는 여기서 끝
        update(body.pid, finished=time.time())
        return {"survey_url": SURVEY_URL.replace("{pid}", body.pid)}
    return {"ok": True}


@app.get("/api/survey")
def survey_items(pid: str):
    row = get(pid)
    if row["survey_order"]:
        order = json.loads(row["survey_order"])
    else:
        order = [it[0] for it in ITEMS]
        random.shuffle(order)
        order.insert(len(order) // 2, ATTENTION[0])
        update(pid, survey_order=json.dumps(order))
    text = {it[0]: it[4] for it in [*ITEMS, ATTENTION]}
    return {"items": [{"code": c, "text": text[c]} for c in order], "scale": SCALE_KO}


class SurveyIn(BaseModel):
    pid: str
    answers: dict[str, int]


@app.post("/api/survey")
def survey(body: SurveyIn):
    row = get(body.pid)
    order = json.loads(row["survey_order"] or "[]")
    if set(body.answers) != set(order) or any(not 1 <= v <= 7 for v in body.answers.values()):
        raise HTTPException(400, "모든 문항에 응답해 주세요")
    code = row["code"] or secrets.token_hex(3).upper()
    update(body.pid, survey=json.dumps(body.answers), finished=time.time(), code=code)
    return {"code": code}


# ───────── 관리자 ─────────
def _check(token):
    if not ADMIN_TOKEN or not secrets.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(403)


@app.get("/admin/db")
def download_db(token: str):
    _check(token)
    snap = DATA_DIR / "experiment_snapshot.db"
    tmp = snap.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    with db() as con:
        con.execute("VACUUM INTO ?", (str(tmp),))
    tmp.replace(snap)
    return FileResponse(snap, filename=f"experiment_{time.strftime('%Y%m%d_%H%M')}.db")


@app.get("/admin/stats")
def stats(token: str):
    _check(token)
    with db() as con:
        rows = con.execute("""SELECT condition, COUNT(*) started, COUNT(shown) recommended,
                              COUNT(finished) finished FROM participants GROUP BY condition""").fetchall()
    return [dict(r) for r in rows]


# ───────── 정적 파일 ─────────
@app.get("/poster/{mid}.jpg")
def poster(mid: str):
    p = BASE / "posters" / f"{mid}.jpg"
    if not re.fullmatch(r"tt\d+", mid) or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
