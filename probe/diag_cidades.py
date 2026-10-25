"""Diagnostico por cidade: a projecao do needle nas maiores cidades (nao apuradas ou parcialmente)
contra a verdade, sob configuracoes de ridge/covariaveis. Dois cenarios:

  replay   needle B no replay de 04/10/2026 (ordem real, feed municipal) aos 3% e 10%; verdade = 1T 2026
  simula   needle A com 10% dos municipios fechados com o voto do 1T (como runner.ciclo2t --simula);
           verdade = a propria ancora (desvio esperado ~0): mede extrapolacao espuria

Uso:  .venv/Scripts/python -m probe.diag_cidades
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from pipeline.needle_hier import Needle, Params
from sintetico.caminhos import BASELINE, SAIDA, UFS

CHAVE = ["uf", "cd_mun", "zona", "secao"]
CONFIGS = {"L=0.005 (atual)": Params(), "L=0.05": Params(L=0.05), "L=0.5": Params(L=0.5),
           "sem covariaveis": Params(usa_cov=False)}
RAIZ_DOCS = __import__("pathlib").Path(__file__).resolve().parents[1] / "docs" / "dados"


def maiores(n=14):
    m = json.loads((SAIDA / "abst_base.json").read_text("utf-8"))["mun"]
    top = sorted(((v.get("aptos26") or 0, int(cd), v["uf"], v["nome"]) for cd, v in m.items()), reverse=True)[:n]
    return [(cd, uf, nome) for _, cd, uf, nome in top]


def tabela(r, truth, cidades, rotulo):
    dfm = r["mun"].set_index(["uf", "cd_mun"])
    linhas = []
    for cd, uf, nome in cidades:
        row = dfm.loc[(uf, cd)]
        proj = 100 * row["esq"] / max(row["esq"] + row["dir"], 1)
        anc = 100 * row["anc_mun"]
        t = truth.get((uf, cd))
        linhas.append(f"{nome[:14]:14s} {uf} apur {100 * row['st'] / max(row['ts'], 1):5.1f}%  anc {anc:5.1f}  proj {proj:5.1f}"
                      + (f"  real {t:5.1f}  erro {proj - t:+5.1f}" if t is not None else ""))
    b = r["br"]
    print(f"  [{rotulo}] nacional: proj {100 * b['dois_esq']:.2f}%  |  " + " | ".join(linhas[:0]))
    for l in linhas:
        print("     ", l)


def main() -> int:
    t0 = time.time()
    cidades = maiores()
    c = pd.read_parquet(BASELINE / "carimbos_presidente_2026_t1.parquet",
                        columns=["uf", "cd_municipio", "zona", "secao", "prim_tot"])
    c["cd_mun"] = c["cd_municipio"].astype(int)
    v = pd.read_parquet(SAIDA / "votos_t1_2026.parquet").merge(c[CHAVE + ["prim_tot"]].drop_duplicates(CHAVE),
                                                                 on=CHAVE, how="left").dropna(subset=["t1_esq", "prim_tot"])
    v["prim_tot"] = pd.to_datetime(v["prim_tot"])
    v = v.sort_values("prim_tot").reset_index(drop=True)
    ts = v.groupby(["uf", "cd_mun"]).size().rename("ts")
    tot = v.groupby(["uf", "cd_mun"])[["t1_esq", "t1_dir"]].sum()
    truth = {k: 100 * r.t1_esq / (r.t1_esq + r.t1_dir) for k, r in tot.iterrows()}

    # ---- replay B
    ancB = pd.read_parquet(SAIDA / "ancora_2026.parquet")
    ndB = Needle(ancB, turno=2)
    print(f"== REPLAY B (verdade = 1T 2026; nacional real {100 * v['t1_esq'].sum() / (v['t1_esq'].sum() + v['t1_dir'].sum()):.2f}%)")
    for pct in (3, 10):
        k = int(round(len(v) * pct / 100))
        g = v.iloc[:k].groupby(["uf", "cd_mun"]).agg(esq=("t1_esq", "sum"), dir=("t1_dir", "sum"), out=("t1_out", "sum"),
                                                     br=("t1_br", "sum"), nu=("t1_nu", "sum"), ea=("aptos", "sum"),
                                                     st=("secao", "size")).reset_index()
        g["bn"] = g["br"] + g["nu"]
        g = g.merge(ts.reset_index(), on=["uf", "cd_mun"], how="left")
        print(f"-- {pct}% apurado")
        for nome, p in CONFIGS.items():
            tabela(ndB.estima(None, g, p), truth, cidades, nome)
    print(f"[{time.time() - t0:.0f}s]")

    # ---- simulacao A (10% dos municipios fechados com o 1T)
    ancA = pd.read_parquet(SAIDA / "ancora_t1_2026.parquet")
    ndA = Needle(ancA, turno=2)
    rng = np.random.default_rng(7)
    rows = []
    for uf in UFS:
        u = json.loads((RAIZ_DOCS / "uf" / f"{uf}.json").read_text("utf-8"))
        for cd, m in u["mun"].items():
            p26 = m.get("pr26t1")
            if not p26 or rng.random() > 0.10:
                continue
            o = json.loads((RAIZ_DOCS / "meta.json").read_text("utf-8")) if False else None
            rows.append({"uf": uf.lower(), "cd_mun": int(cd), "st": m["ns"], "ts": m["ns"], "ea": m["aptos26"], "m": m})
    # ordem real dos candidatos no pr26t1: 22 primeiro, 13 segundo (meta.pr.r26.t1)
    meta = json.loads((RAIZ_DOCS / "meta.json").read_text("utf-8"))
    ordem = [x[0] for x in meta["pr"]["r26"]["t1"]]
    i13, i22, n26 = ordem.index("13"), ordem.index("22"), len(ordem)
    feed = []
    for r in rows:
        p = r["m"]["pr26t1"]
        esq, dir_ = p[i13], p[i22]
        out = sum(p[i] for i in range(n26) if i not in (i13, i22))
        feed.append({"uf": r["uf"], "cd_mun": r["cd_mun"], "esq": esq, "dir": dir_, "out": out,
                     "bn": p[n26] + p[n26 + 1], "ea": r["ea"], "st": r["st"], "ts": r["ts"]})
    feed = pd.DataFrame(feed)
    anc_truth = {}
    e0, d0 = ndA.esp0["esq"], ndA.esp0["dois"]
    for cd, uf, nome in cidades:
        j = ndA.mun_idx[f"{uf}:{cd}"]
        sel = ndA.mun_cod == j
        anc_truth[(uf, cd)] = 100 * e0[sel].sum() / d0[sel].sum()
    print(f"== SIMULACAO A (10% dos municipios fechados; verdade = a ancora, nacional {100 * e0.sum() / d0.sum():.2f}%)")
    for nome, p in CONFIGS.items():
        tabela(ndA.estima(None, feed, p), anc_truth, cidades, nome)
    print(f"[{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
