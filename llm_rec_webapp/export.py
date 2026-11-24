"""
experiment.db → 분석용 CSV 3개
  participants.csv : 참가자별 1행 (조건, 질의, 선택, 소요시간 [+ 웹앱 설문을 썼다면 문항 점수])
                     구글 설문을 쓴 경우: 구글 설문 응답 CSV와 pid(참가자 번호)로 합치기
  item_ratings.csv : 참가자 × 추천 영화 10편 (본 적 있음, 선호 1-5, 요청 일치, LLM 순위, 선택 여부, 감정 점수)
  manipulation.csv : 참가자별 AESR / AEED / AGHD (LLM 감정 점수 기준)

  python export.py [experiment.db 경로]
"""
import json
import sqlite3
import sys

import pandas as pd

import recommender as R
from questionnaire import ATTENTION, ATTENTION_ANSWER, ITEMS

con = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "experiment.db")
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute("SELECT * FROM participants WHERE finished IS NOT NULL")]

P, I, M = [], [], []
for r in rows:
    shown = json.loads(r["shown"])
    by_key = {c["key"]: c for c in shown}
    keys = [c["key"] for c in shown]
    ans = json.loads(r["survey"]) if r["survey"] else None
    log = json.loads(r["rec_log"])

    rec = {"pid": r["pid"], "ext_id": r["ext_id"], "condition": r["condition"], "query": r["query"],
           "choice": r["choice"], "choice_title": by_key[r["choice"]]["title"],
           "choice_pos": keys.index(r["choice"]) + 1,
           "n_candidates": len(log.get("candidates", [])), "n_not_found": len(log.get("not_found", [])),
           "llm_calls": len(log.get("raw_responses", [])),
           "rec_seconds": r["rec_seconds"], "total_minutes": round((r["finished"] - r["created"]) / 60, 1)}
    if ans:
        rec["attention_ok"] = ans.get(ATTENTION[0]) == ATTENTION_ANSWER
        for code, cons, rev, _, _ in ITEMS:
            rec[code] = 8 - ans[code] if rev else ans[code]          # 역문항 변환
        for cons in {it[1] for it in ITEMS}:
            rec[f"{cons}_mean"] = round(sum(rec[it[0]] for it in ITEMS if it[1] == cons)
                                        / sum(1 for it in ITEMS if it[1] == cons), 3)
    P.append(rec)

    for x in json.loads(r["ratings"]):
        c = by_key[x["id"]]
        I.append({"pid": r["pid"], "condition": r["condition"], "movie_key": x["id"], "title": c["title"],
                  "year": c["year"], "genres": c["genres"], "display_pos": keys.index(x["id"]) + 1,
                  "llm_rank": c["llm_rank"], "seen": x["seen"], "like": x["like"], "fit": x["fit"],
                  "chosen": x["id"] == r["choice"], **{f"emo_{e}": c["emotions"][e] for e in R.EMOTIONS}})
    M.append({"pid": r["pid"], "condition": r["condition"],
              "AESR": R.aesr(shown), "AEED": R.aeed(shown), "AGHD": R.aghd(shown)})

pd.DataFrame(P).to_csv("participants.csv", index=False)
pd.DataFrame(I).to_csv("item_ratings.csv", index=False)
pd.DataFrame(M).to_csv("manipulation.csv", index=False)
print(f"완료한 참가자 {len(P)}명 내보냄")
if M:
    print(pd.DataFrame(M).groupby("condition")[["AESR", "AEED", "AGHD"]].agg(["mean", "count"]).round(3))
