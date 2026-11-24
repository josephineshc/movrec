"""
오프라인 시뮬레이션: 가상 사용자로 세 조건을 돌려 조작 점검 지표 비교

  export GEMINI_API_KEY=...  TMDB_API_KEY=...
  python simulate.py movies.csv sim_results.json

무료 한도 아끼기: 가상 사용자 1명당 Gemini 2번 호출
  (30편 요청 1번 → baseline과 emotion_div가 같은 후보 사용, prompt_div 12편 요청 1번)
  호출 사이 쉬는 시간: export SIM_PAUSE=20
"""
import json
import os
import sys
import time

import pandas as pd

import recommender as R

USERS = [
    (["Inception", "Interstellar", "The Prestige", "Memento", "The Dark Knight"],
     "Something mind-bending with a clever twist"),
    (["The Notebook", "La La Land", "About Time", "Pride & Prejudice", "Her"],
     "비 오는 주말에 혼자 보기 좋은 로맨스 영화"),
    (["The Conjuring", "Insidious", "Sinister", "It Follows", "Get Out"],
     "I want a horror movie that isn't just jump scares"),
    (["Toy Story 3", "Up", "Inside Out", "Coco", "Zootopia"],
     "가족이랑 같이 볼 애니메이션"),
    (["Mad Max: Fury Road", "John Wick", "The Raid: Redemption", "Gladiator", "Edge of Tomorrow"],
     "Action movies directed by Christopher Nolan"),
    (["Spotlight", "The Social Network", "Moneyball", "The Big Short", "Zodiac"],
     "실화를 바탕으로 한 영화"),
]


def find(titles, movies):
    out = []
    for t in titles:
        hit = movies[movies["title"].str.lower() == t.lower()]
        if hit.empty:
            raise ValueError(f"데이터셋에 없는 영화: {t}")
        m = hit.sort_values("year").iloc[-1]
        out.append({"title": m["title"], "year": int(m["year"]), "genres": m["genres"], "plot": m["plot"]})
    return out


def main(movies_path, out_path):
    movies = R.load_movies(movies_path)
    llm, tmdb = R.Gemini(), R.Tmdb()
    pause = float(os.environ.get("SIM_PAUSE", "0"))
    rows, logs = [], []

    for titles, query in USERS:
        liked = find(titles, movies)
        res = {}
        for cond in ("baseline", "prompt_div"):
            res[cond] = R.recommend(cond, query, liked, llm, tmdb)
            time.sleep(pause)
        # emotion_div: baseline과 같은 30편 후보에 다양화만 적용 (추가 호출 없음)
        cands = res["baseline"].log["candidates"]
        picked = {c["key"] for c in R.diversify(cands)}
        res["emotion_div"] = R.Result("emotion_div", [c for c in cands if c["key"] in picked], res["baseline"].log)

        for cond, r in res.items():
            rows.append({"query": query, "condition": cond, "AESR": R.aesr(r.shown), "AEED": R.aeed(r.shown),
                         "AGHD": R.aghd(r.shown), "seconds": r.log["seconds"],
                         "not_found": len(r.log.get("not_found", [])), "calls": len(r.log["raw_responses"])})
            logs.append({"query": query, "condition": cond, "titles": [f"{c['title']} ({c['year']})" for c in r.shown],
                         "not_found": r.log.get("not_found", [])})
            print(f"[{cond:11}] {query[:30]:30} → {', '.join(c['title'] for c in r.shown[:4])}…")

    df = pd.DataFrame(rows)
    print("\n조건별 평균")
    print(df.groupby("condition")[["AESR", "AEED", "AGHD", "seconds", "not_found", "calls"]].mean().round(3))
    json.dump(logs, open(out_path, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
