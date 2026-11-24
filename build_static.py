"""
GitHub Pages용 데이터 만들기 → docs/data/, docs/posters/

  python build_static.py movies.csv als_model.npz posters

만드는 파일
  docs/data/movies.json  : 영화 7,504편 (ID, 제목, 연도, 장르, 줄거리 40단어, 감정 시그니처 8개)
  docs/data/als.json     : ALS 모델 정보 (영화 ID 순서, 영화 편향, 평균, 정규화 값, 요인 수)
  docs/data/als_q.bin    : ALS 영화 요인 행렬 (float32)
  docs/data/survey.json  : 목록별 설문 문항 (questionnaire.py 의 SURVEY_ITEMS)
  docs/posters/*.jpg     : 선호작 고르기 화면용 포스터
"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

EMOTIONS = ["joy", "trust", "fear", "surprise", "sadness", "disgust", "anger", "anticipation"]


def main(movies_path, als_path, posters_dir, out="docs"):
    out = Path(out)
    (out / "data").mkdir(parents=True, exist_ok=True)

    m = pd.read_csv(movies_path)
    cols = ["id", "title", "year", "genres", "plot"] + EMOTIONS
    rows = [[r["id"], r["title"], int(r["year"]), r["genres"], r["plot"]] + [round(float(r[e]), 6) for e in EMOTIONS]
            for _, r in m.iterrows()]
    (out / "data" / "movies.json").write_text(json.dumps({"cols": cols, "rows": rows}, ensure_ascii=False,
                                                          separators=(",", ":")))

    z = np.load(als_path)
    Q = z["Q"].astype("<f4")
    meta = {"ids": [str(x) for x in z["ids"]], "bi": [round(float(x), 6) for x in z["bi"]],
            "mu": float(z["mu"]), "reg": float(z["reg"]), "k": int(Q.shape[1])}
    (out / "data" / "als.json").write_text(json.dumps(meta, separators=(",", ":")))
    (out / "data" / "als_q.bin").write_bytes(Q.tobytes(order="C"))

    from questionnaire import ATTENTION, ATTENTION_ANSWER, SCALE_KO, SURVEY_ITEMS
    survey = {"items": [{"code": c, "construct": k, "reverse": rv, "text": ko} for c, k, rv, _, ko in SURVEY_ITEMS],
              "attention": {"code": ATTENTION[0], "answer": ATTENTION_ANSWER}, "scale": SCALE_KO}
    (out / "data" / "survey.json").write_text(json.dumps(survey, ensure_ascii=False, indent=1))

    dst = out / "posters"
    if Path(posters_dir).resolve() != dst.resolve():
        shutil.copytree(posters_dir, dst, dirs_exist_ok=True)

    print(f"영화 {len(rows)}편, ALS {Q.shape[0]}편 × {Q.shape[1]}요인, 포스터 {len(list(dst.glob('*.jpg')))}장 → {out}/")


if __name__ == "__main__":
    main(*sys.argv[1:4])
