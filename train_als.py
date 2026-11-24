"""
감정 다양화 조건용 평점 모델(ALS) 학습 — Lansman et al. (2025) 방식
MovieLens 25M 평점으로 편향 포함 행렬 분해(명시적 ALS)를 학습하고 als_model.npz 로 저장.
실험 중에는 참가자가 고른 선호 영화 5편(각 5점으로 간주)으로 사용자 벡터를 구해(fold-in) 상위 200편을 뽑는다.

준비: https://grouplens.org/datasets/movielens/25m/ 에서 ml-25m.zip 받아 풀기 (ratings.csv 사용)

  python train_als.py ml-25m/ratings.csv movies.csv als_model.npz

옵션 (환경변수):
  ALS_FACTORS=50  ALS_REG=0.1  ALS_ITERS=10
  ALS_MAX_USERS=30000   학습에 쓸 사용자 수 (무작위 추출, 0이면 전부). 원 논문 최종 데이터: 7,384명
"""
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

FACTORS = int(os.environ.get("ALS_FACTORS", 50))
REG = float(os.environ.get("ALS_REG", 0.1))
ITERS = int(os.environ.get("ALS_ITERS", 10))
MAX_USERS = int(os.environ.get("ALS_MAX_USERS", 30000))
MIN_USER_RATINGS = 20


def solve_rows(R: csr_matrix, other: np.ndarray, other_bias: np.ndarray, mu: float, reg: float):
    """각 행(사용자 또는 영화)에 대해 [편향, 요인] 을 릿지 회귀로 구함"""
    n, k = R.shape[0], other.shape[1]
    out_bias, out_f = np.zeros(n), np.zeros((n, k))
    X_all = np.hstack([np.ones((other.shape[0], 1)), other])
    eye = reg * np.eye(k + 1)
    for r in range(n):
        s, e = R.indptr[r], R.indptr[r + 1]
        if s == e:
            continue
        idx, y = R.indices[s:e], R.data[s:e] - mu - other_bias[R.indices[s:e]]
        X = X_all[idx]
        sol = np.linalg.solve(X.T @ X + eye * len(idx), X.T @ y)
        out_bias[r], out_f[r] = sol[0], sol[1:]
    return out_bias, out_f


def train(ratings: pd.DataFrame, n_items: int, seed=0):
    """ratings: columns u (0..n_users-1), i (0..n_items-1), r"""
    rng = np.random.default_rng(seed)
    n_users = ratings["u"].max() + 1
    mu = ratings["r"].mean()
    Ru = csr_matrix((ratings["r"].to_numpy(float), (ratings["u"], ratings["i"])), shape=(n_users, n_items))
    Ri = Ru.T.tocsr()
    P = rng.normal(0, 0.1, (n_users, FACTORS))
    Q = rng.normal(0, 0.1, (n_items, FACTORS))
    bu, bi = np.zeros(n_users), np.zeros(n_items)
    for it in range(ITERS):
        t = time.time()
        bu, P = solve_rows(Ru, Q, bi, mu, REG)
        bi, Q = solve_rows(Ri, P, bu, mu, REG)
        pred = mu + bu[ratings["u"]] + bi[ratings["i"]] + np.einsum("ij,ij->i", P[ratings["u"]], Q[ratings["i"]])
        rmse = np.sqrt(np.mean((pred - ratings["r"]) ** 2))
        print(f"  반복 {it + 1}/{ITERS}  학습 RMSE {rmse:.4f}  ({time.time() - t:.0f}s)")
    return mu, bi, Q


def main(ratings_path, movies_path, out_path):
    movies = pd.read_csv(movies_path)
    ml2id = dict(zip(movies["movielens_id"], movies["id"]))
    print("평점 읽는 중...")
    df = pd.read_csv(ratings_path, usecols=["userId", "movieId", "rating"])
    df = df[df["movieId"].isin(ml2id)]
    counts = df["userId"].value_counts()
    users = counts[counts >= MIN_USER_RATINGS].index.to_numpy()
    if MAX_USERS and len(users) > MAX_USERS:
        users = np.random.default_rng(0).choice(users, MAX_USERS, replace=False)
    df = df[df["userId"].isin(users)]

    item_ids = sorted(df["movieId"].unique())
    imap = {m: i for i, m in enumerate(item_ids)}
    umap = {u: i for i, u in enumerate(df["userId"].unique())}
    ratings = pd.DataFrame({"u": df["userId"].map(umap).to_numpy(), "i": df["movieId"].map(imap).to_numpy(),
                            "r": df["rating"].to_numpy(float)})
    print(f"학습: 사용자 {len(umap):,}명, 영화 {len(item_ids):,}편, 평점 {len(ratings):,}개")
    mu, bi, Q = train(ratings, len(item_ids))
    np.savez_compressed(out_path, ids=np.array([ml2id[m] for m in item_ids], dtype=str), Q=Q, bi=bi, mu=mu, reg=REG)
    print(f"저장: {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
