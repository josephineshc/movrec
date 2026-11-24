"""
응답 DB → 분석용 표 (웹앱의 /admin/csv 도 같은 함수를 씀)

  python export.py experiment.db       →  responses.csv, item_ratings.csv

  responses.csv    : 참가자 × 목록 2개 (한 줄 = 한 목록)
                     순서 코드(A/B), 목록 위치, 방법(gemini/emotion), 질의, 선택한 영화,
                     평가 요약, 조작 점검 지표, 설문 문항 원점수 + 구성개념 평균(역문항 변환), 주의 확인, 자유 의견
  item_ratings.csv : 참가자 × 목록 × 영화 10편
"""
import json
import sqlite3
import sys

import pandas as pd

import recommender as R
from questionnaire import ATTENTION, ATTENTION_ANSWER, SCORED_ITEMS

ORDER_CODE = {"gemini,emotion": "A", "emotion,gemini": "B"}


def tables(rows: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    resp, items = [], []
    for r in rows:
        if not r.get("lists"):
            continue
        order = r["list_order"].split(",")
        lists = json.loads(r["lists"])
        choices = json.loads(r["choices"] or "{}")
        ratings = json.loads(r["ratings"] or "{}")
        surveys = json.loads(r["surveys"] or "{}")
        for pos, m in enumerate(order, 1):
            keys = [c["key"] for c in lists[m]]
            by_key = {c["key"]: c for c in lists[m]}
            ch = choices.get(m, {}).get("key")
            rt = ratings.get(m, [])
            sv = surveys.get(m, {})
            rec = {"pid": r["pid"], "ext_id": r["ext_id"], "order_code": ORDER_CODE[r["list_order"]],
                   "list_pos": pos, "method": m, "finished": bool(r["finished"]), "query": r["query"],
                   "choice_title": by_key[ch]["title"] if ch else None,
                   "choice_pos": keys.index(ch) + 1 if ch else None,
                   "mean_like": round(sum(x["like"] for x in rt) / len(rt), 2) if rt else None,
                   "fit_rate": round(sum(x["fit"] for x in rt) / len(rt), 2) if rt else None,
                   "seen_n": sum(x["seen"] for x in rt) if rt else None,
                   "sig_n": R.coverage(lists[m]), "AESR": R.aesr(lists[m]), "AEED": R.aeed(lists[m]),
                   "AGHD": R.aghd(lists[m]),
                   "attention_ok": sv.get(ATTENTION[0]) == ATTENTION_ANSWER if sv else None}
            for code, _, rev, _, _ in SCORED_ITEMS:               # 원점수 그대로
                rec[code] = sv.get(code)
            for cons in dict.fromkeys(it[1] for it in SCORED_ITEMS):  # 구성개념 평균 (역문항 8-점수)
                vals = [8 - sv[c] if rev else sv[c] for c, k, rev, _, _ in SCORED_ITEMS if k == cons and c in sv]
                rec[f"{cons}_mean"] = round(sum(vals) / len(vals), 3) if vals else None
            rec["comment"] = r["comment"]
            resp.append(rec)
            for x in rt:
                c, sig = by_key[x["id"]], by_key[x["id"]].get("signature") or {}
                items.append({"pid": r["pid"], "order_code": ORDER_CODE[r["list_order"]], "list_pos": pos,
                              "method": m, "movie_key": x["id"], "imdb_id": c.get("imdb_id"), "title": c["title"],
                              "year": c["year"], "genres": c["genres"], "display_pos": keys.index(x["id"]) + 1,
                              "source_rank": c["rank"], "seen": x["seen"], "like": x["like"], "fit": x["fit"],
                              "chosen": x["id"] == ch, **{f"emo_{e}": sig.get(e) for e in R.EMOTIONS}})
    return pd.DataFrame(resp), pd.DataFrame(items)


if __name__ == "__main__":
    con = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "experiment.db")
    con.row_factory = sqlite3.Row
    resp, items = tables([dict(r) for r in con.execute("SELECT * FROM sessions")])
    resp.to_csv("responses.csv", index=False)
    items.to_csv("item_ratings.csv", index=False)
    done = resp[resp["finished"]]
    print(f"완료 {done['pid'].nunique()}명 (전체 {resp['pid'].nunique()}명) → responses.csv, item_ratings.csv")
