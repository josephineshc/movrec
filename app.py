"""
실험 웹앱 서버 — 참가자 내 설계 (한 참가자가 추천 목록 2개를 모두 봄)

  목록 종류: gemini  (Gemini가 선호작 5편 + 질의로 자유 추천, 상위 10편)
             emotion (원 논문: ALS 상위 200편 → 감정 시그니처 다양화 10편)
  순서: 참가자마다 gemini 먼저 / emotion 먼저를 번갈아 배정 (순서 효과 상쇄)
  흐름: 선호작 5편 → 질의 → 목록 1 선택·평가·설문 → 목록 2 선택·평가·설문(+자유 의견) → 완료
  응답(순서 코드 포함)은 제출할 때마다 DB에 저장. 표로 받기: /admin/csv?token=...

실행:
  pip install -r requirements.txt
  export GEMINI_API_KEY=...  TMDB_API_KEY=...
  uvicorn app:app --port 8000          # → http://localhost:8000
가짜 모드 (Gemini·TMDB 없이 화면 흐름만 시험):  MOCK=1 uvicorn app:app --port 8000

필요한 파일: movies.csv, posters/<id>.jpg, als_model.npz (train_als.py)
환경변수 (선택):
  DATA_DIR    응답 DB 저장 폴더 (호스팅 시 영구 볼륨 경로, 예: /data)
  ADMIN_TOKEN /admin/csv, /admin/db, /admin/stats 비밀번호
  SHEETS_URL, SHEETS_SECRET  구글 시트 저장용 Apps Script 웹 앱 주소와 비밀값 (sheets_webhook.gs)
                             설문을 제출할 때마다 응답을 시트에 추가 (무료 서버는 재시작 때 DB가 지워지므로)
순서 코드: A = 첫 번째 Gemini·두 번째 감정 / B = 첫 번째 감정·두 번째 Gemini
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

import io

from fastapi.responses import StreamingResponse

import recommender as R
from export import ORDER_CODE, tables
from questionnaire import ATTENTION, SCALE_KO, SURVEY_ITEMS

BASE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "experiment.db"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")
MOCK = os.environ.get("MOCK") == "1"
SHEETS_URL = os.environ.get("SHEETS_URL")
SHEETS_SECRET = os.environ.get("SHEETS_SECRET", "")

METHODS = {"gemini": "baseline", "emotion": "emotion_div"}      # 목록 이름 → recommender 조건
ORDERS = tuple(ORDER_CODE)                                      # A: gemini 먼저, B: emotion 먼저

movies = R.load_movies(BASE / "movies.csv")
_title_lc = movies["title"].str.lower()


# ───────── Gemini·TMDB·ALS (진짜 / 가짜) ─────────
class MockLLM:
    """화면 테스트용: 데이터셋에서 무작위 영화 12편"""
    def generate_json(self, prompt):
        time.sleep(1.5)
        rng = random.Random(prompt)
        pick = movies[movies["year"] >= R.MIN_YEAR].sample(R.N_REQUEST, random_state=rng.randrange(10**6))
        return [{"title": m.title, "year": int(m.year)} for m in pick.itertuples()]


class MockTmdb:
    def _card(self, m):
        return {"tmdb_id": int(m["id"][2:]), "title": m["title"], "year": int(m["year"]), "imdb_id": m["id"],
                "poster": f"/poster/{m['id']}.jpg", "plot": m["plot"], "genres": m["genres"]}

    def search(self, title, year):
        hit = movies[(_title_lc == title.lower()) & (movies["year"] == year)]
        return None if hit.empty else self._card(hit.iloc[0])

    def find_imdb(self, imdb_id):
        return self._card(movies.loc[imdb_id]) if imdb_id in movies.index else None


def mock_als():
    import numpy as np
    path = DATA_DIR / "mock_als.npz"
    rng = np.random.default_rng(0)
    np.savez(path, ids=movies.index.to_numpy().astype(str), Q=rng.normal(0, .3, (len(movies), 20)),
             bi=rng.normal(0, .3, len(movies)), mu=3.5, reg=0.1)
    return R.ALS(path)


if MOCK:
    llm, tmdb, als = MockLLM(), MockTmdb(), mock_als()
    print("⚠️  MOCK 모드: 추천 결과는 의미 없음")
else:
    llm, tmdb, als = R.Gemini(), R.Tmdb(), R.ALS(BASE / "als_model.npz")


# ───────── 구글 시트로 보내기 ─────────
def _clean(records):
    import math
    return [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()} for r in records]


def push_to_sheets(sheets: dict):
    """백그라운드에서 전송 (참가자를 기다리게 하지 않음). 실패하면 5번까지 재시도."""
    if not SHEETS_URL:
        return
    body = json.dumps({"secret": SHEETS_SECRET, "sheets": sheets}, ensure_ascii=False, default=str)

    def send():
        import httpx
        for attempt in range(5):
            try:
                r = httpx.post(SHEETS_URL, content=body, headers={"Content-Type": "application/json"},
                               follow_redirects=True, timeout=30)
                if r.status_code == 200 and r.json().get("ok"):
                    return
                print("시트 저장 실패:", r.status_code, r.text[:200])
            except Exception as e:
                print("시트 저장 오류:", repr(e))
            time.sleep(5 * (attempt + 1))
        print("⚠️ 시트 저장 최종 실패:", body[:300])

    threading.Thread(target=send, daemon=True).start()


if not SHEETS_URL:
    print("⚠️  SHEETS_URL 없음: 응답이 이 서버의 DB에만 저장됨")


# ───────── DB ─────────
_lock = threading.Lock()


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


with db() as con:
    con.execute("""CREATE TABLE IF NOT EXISTS sessions (
        pid TEXT PRIMARY KEY, list_order TEXT, created REAL, ext_id TEXT,
        liked TEXT, query TEXT, lists TEXT, rec_log TEXT, rec_seconds REAL,
        choices TEXT, ratings TEXT, finished REAL)""")
    have = {r[1] for r in con.execute("PRAGMA table_info(sessions)")}
    for col in ("order_code TEXT", "survey_orders TEXT", "surveys TEXT", "comment TEXT"):
        if col.split()[0] not in have:
            con.execute(f"ALTER TABLE sessions ADD COLUMN {col}")


def update(pid, **fields):
    cols = ", ".join(f"{k}=?" for k in fields)
    with _lock, db() as con:
        cur = con.execute(f"UPDATE sessions SET {cols} WHERE pid=?", (*fields.values(), pid))
        if cur.rowcount == 0:
            raise HTTPException(404, "참가자를 찾을 수 없어요")


def get(pid):
    with db() as con:
        row = con.execute("SELECT * FROM sessions WHERE pid=?", (pid,)).fetchone()
    if not row:
        raise HTTPException(404, "참가자를 찾을 수 없어요")
    return row


def assign_order(con) -> str:
    """두 순서 중 인원이 적은 쪽 (동률이면 무작위)"""
    counts = {o: 0 for o in ORDERS}
    for r in con.execute("SELECT list_order, COUNT(*) n FROM sessions GROUP BY list_order"):
        counts[r["list_order"]] = r["n"]
    least = min(counts.values())
    return random.choice([o for o, n in counts.items() if n == least])


def method_at(row, idx: int) -> str:
    """화면의 목록 번호(0, 1) → 방법 이름"""
    if idx not in (0, 1):
        raise HTTPException(400, "목록 번호가 잘못됐어요")
    return row["list_order"].split(",")[idx]


def jload(row, col, default):
    return json.loads(row[col]) if row[col] else default


def dataset_card(mid):
    m = movies.loc[mid]
    return {"id": mid, "title": m["title"], "year": int(m["year"]), "genres": m["genres"], "plot": m["plot"]}


def rec_card(c):
    """화면에 보내는 정보 (출처·순위·감정 점수는 보내지 않음)"""
    return {"id": c["key"], "title": c["title"], "year": c["year"], "genres": c["genres"],
            "plot": c["plot"], "poster": c.get("poster")}


def lists_for_screen(row):
    lists = jload(row, "lists", {})
    return [[rec_card(c) for c in lists[m]] for m in row["list_order"].split(",")]


# ───────── API ─────────
app = FastAPI()


class StartIn(BaseModel):
    ext_id: str | None = None


@app.post("/api/start")
def start(body: StartIn):
    pid = secrets.token_hex(8)
    with _lock, db() as con:
        order = assign_order(con)
        con.execute("INSERT INTO sessions (pid, list_order, order_code, created, ext_id) VALUES (?,?,?,?,?)",
                    (pid, order, ORDER_CODE[order], time.time(), body.ext_id))
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
    """두 목록을 한 번에 만들어 화면 순서대로 돌려줌"""
    row = get(body.pid)
    if row["lists"]:                                  # 새로고침해도 같은 결과
        return {"lists": lists_for_screen(row)}
    if len(set(body.liked)) != 5 or any(m not in movies.index for m in body.liked):
        raise HTTPException(400, "좋아하는 영화 5편을 골라 주세요")
    if len(body.query.strip()) < 5:
        raise HTTPException(400, "요청을 조금 더 자세히 적어 주세요")
    if body.pid in _busy:
        raise HTTPException(429, "추천을 만드는 중이에요. 잠시만 기다려 주세요")
    _busy.add(body.pid)
    try:
        t0 = time.time()
        res = {name: R.recommend(cond, body.query.strip(), body.liked, movies, llm, tmdb, als)
               for name, cond in METHODS.items()}
    except Exception as e:
        print("추천 실패:", body.pid, repr(e))
        raise HTTPException(503, "추천을 만들지 못했어요. 잠시 후 다시 시도해 주세요")
    finally:
        _busy.discard(body.pid)
    update(body.pid, liked=json.dumps(body.liked), query=body.query.strip(),
           lists=json.dumps({k: r.shown for k, r in res.items()}, ensure_ascii=False),
           rec_log=json.dumps({k: r.log for k, r in res.items()}, ensure_ascii=False),
           rec_seconds=round(time.time() - t0, 2))
    return {"lists": lists_for_screen(get(body.pid))}


class ChoiceIn(BaseModel):
    pid: str
    list_idx: int
    movie_id: str


@app.post("/api/choice")
def choice(body: ChoiceIn):
    row = get(body.pid)
    m = method_at(row, body.list_idx)
    if body.movie_id not in [c["key"] for c in jload(row, "lists", {}).get(m, [])]:
        raise HTTPException(400, "추천 목록에 없는 영화예요")
    choices = jload(row, "choices", {})
    choices[m] = {"key": body.movie_id, "time": time.time()}
    update(body.pid, choices=json.dumps(choices))
    return {"ok": True}


class Rating(BaseModel):
    id: str
    seen: bool
    like: int          # 1-5
    fit: bool          # 내 요청에 맞는지


class RatingsIn(BaseModel):
    pid: str
    list_idx: int
    ratings: list[Rating]


@app.post("/api/ratings")
def ratings(body: RatingsIn):
    row = get(body.pid)
    m = method_at(row, body.list_idx)
    keys = [c["key"] for c in jload(row, "lists", {}).get(m, [])]
    if sorted(r.id for r in body.ratings) != sorted(keys) or any(not 1 <= r.like <= 5 for r in body.ratings):
        raise HTTPException(400, "모든 영화에 응답해 주세요")
    all_r = jload(row, "ratings", {})
    all_r[m] = [r.model_dump() for r in body.ratings]
    update(body.pid, ratings=json.dumps(all_r))
    return {"ok": True}


@app.get("/api/survey")
def survey_items(pid: str, list_idx: int):
    """목록별 설문 문항 (참가자·목록마다 순서를 섞고 저장, 주의 확인 문항은 중간에)"""
    row = get(pid)
    m = method_at(row, list_idx)
    orders = jload(row, "survey_orders", {})
    if m not in orders:
        codes = [it[0] for it in SURVEY_ITEMS if it[0] != ATTENTION[0]]
        random.shuffle(codes)
        codes.insert(len(codes) // 2, ATTENTION[0])
        orders[m] = codes
        update(pid, survey_orders=json.dumps(orders))
    text = {it[0]: it[4] for it in SURVEY_ITEMS}
    return {"items": [{"code": c, "text": text[c]} for c in orders[m]], "scale": SCALE_KO}


class SurveyIn(BaseModel):
    pid: str
    list_idx: int
    answers: dict[str, int]
    comment: str | None = None


@app.post("/api/survey")
def survey(body: SurveyIn):
    row = get(body.pid)
    m = method_at(row, body.list_idx)
    codes = jload(row, "survey_orders", {}).get(m, [])
    if not codes or set(body.answers) != set(codes) or any(not 1 <= v <= 7 for v in body.answers.values()):
        raise HTTPException(400, "모든 문항에 응답해 주세요")
    surveys = jload(row, "surveys", {})
    surveys[m] = body.answers
    fields = {"surveys": json.dumps(surveys)}
    if body.list_idx == 1:                           # 두 번째 목록 설문까지 끝
        fields |= {"comment": (body.comment or "").strip()[:5000], "finished": time.time()}
    update(body.pid, **fields)

    # 이 목록의 응답을 구글 시트로
    row = dict(get(body.pid))
    resp, items = tables([row])
    pos = body.list_idx + 1
    sheets = {"responses": _clean(resp[resp["list_pos"] == pos].drop(columns=["finished"]).to_dict("records")),
              "items": _clean(items[items["list_pos"] == pos].to_dict("records")) if len(items) else []}
    if body.list_idx == 1:                           # 마지막에 전체 기록 백업
        sheets["raw"] = [{"pid": row["pid"], "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "record": json.dumps({k: row[k] for k in row if k != "rec_log"}, ensure_ascii=False)[:49000]}]
    push_to_sheets(sheets)
    return {"ok": True}


@app.get("/api/ping")
def ping():
    """참가자가 화면을 열어 두는 동안 무료 서버가 잠들지 않게"""
    return {"ok": True}


# ───────── 관리자 ─────────
def _check(token):
    if not ADMIN_TOKEN or not secrets.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(403)


@app.get("/admin/csv")
def download_csv(token: str, kind: str = "responses"):
    """kind=responses (참가자×목록, 설문 포함) 또는 kind=items (영화별 평가)"""
    _check(token)
    with db() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM sessions")]
    resp, items = tables(rows)
    df = items if kind == "items" else resp
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    name = f"{'item_ratings' if kind == 'items' else 'responses'}_{time.strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(iter(["\ufeff" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={name}"})


@app.get("/admin/db")
def download_db(token: str):
    _check(token)
    snap, tmp = DATA_DIR / "experiment_snapshot.db", DATA_DIR / "experiment_snapshot.tmp"
    tmp.unlink(missing_ok=True)
    with db() as con:
        con.execute("VACUUM INTO ?", (str(tmp),))
    tmp.replace(snap)
    return FileResponse(snap, filename=f"experiment_{time.strftime('%Y%m%d_%H%M')}.db")


@app.get("/admin/stats")
def stats(token: str):
    _check(token)
    with db() as con:
        rows = con.execute("""SELECT list_order, COUNT(*) started, COUNT(lists) recommended,
                              COUNT(finished) finished FROM sessions GROUP BY list_order""").fetchall()
    return [dict(r) for r in rows]


# ───────── 정적 파일 ─────────
@app.get("/poster/{mid}.jpg")
def poster(mid: str):
    p = BASE / "posters" / f"{mid}.jpg"
    if not re.fullmatch(r"tt\d+", mid) or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
