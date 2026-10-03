"""Calibra o needle hierarquico no replay do 1o turno de 2022, sem olhar a resposta.

Ancora = 2o turno de 2018 por secao + deriva demografica 2018->2022 (coeficientes de 2018),
ou seja, exatamente a informacao que existia antes da noite. As urnas entram na ordem real
de totalizacao (carimbos). Em cada marco de % apurado:

  feed  = soma exata das urnas ja totalizadas, por municipio (o que o -u diria)
  obs   = subconjunto "raspado" das totalizadas: fracao rho, com atraso `lag` minutos

Compara com a tela crua e com o needle validado (pipeline/modelo.py:projeta).
Metrica: erro da margem esq-dir nos validos (pontos), contra o final real (+5,23).

Uso:  .venv/Scripts/python -m probe.calibra_hier [--grade] [--rho 0,0.5,1]
"""
from __future__ import annotations

import itertools
import sys
import time

import numpy as np
import pandas as pd

from pipeline.modelo import monta as monta_v1, projeta as projeta_v1
from pipeline.needle_hier import Needle, Params
from sintetico.caminhos import BASELINE, SAIDA

CHAVE = ["uf", "cd_mun", "zona", "secao"]
MARCOS = [0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30, 50, 70]


def prepara(turno: int = 1):
    anc = pd.read_parquet(SAIDA / "ancora_2022_calib.parquet")
    v = pd.read_parquet(BASELINE / "presidente_secao_2022.parquet")
    v["cd_mun"] = v["cd_municipio"].astype(int)
    c = pd.read_parquet(BASELINE / f"carimbos_presidente_2022_t{turno}.parquet")
    c["cd_mun"] = c["cd_municipio"].astype(int)
    t = f"t{turno}_"
    cols = [t + "esq", t + "dir", t + "branco", t + "nulo"] + ([t + "outros"] if turno == 1 else [])
    df = anc[CHAVE].merge(v[CHAVE + cols], on=CHAVE, how="left").merge(
        c[CHAVE + ["prim_tot", "aptos"]].rename(columns={"aptos": "aptos_c"}), on=CHAVE, how="left")
    assert len(df) == len(anc)
    tr = {"esq": df[t + "esq"].fillna(0).to_numpy(float), "dir": df[t + "dir"].fillna(0).to_numpy(float),
          "out": (df[t + "outros"].fillna(0).to_numpy(float) if turno == 1 else np.zeros(len(df))),
          "bn": (df[t + "branco"] + df[t + "nulo"]).fillna(0).to_numpy(float),
          "apt": df["aptos_c"].fillna(0).to_numpy(float)}
    tr["tempo"] = df["prim_tot"].to_numpy()
    tem = df[t + "esq"].notna() & df["prim_tot"].notna()
    tr["tem"] = tem.to_numpy()
    val = tr["esq"] + tr["dir"] + tr["out"]
    tr["final_margem"] = 100 * (tr["esq"].sum() - tr["dir"].sum()) / val.sum()
    tr["final_uf"] = (pd.DataFrame({"uf": df["uf"], "e": tr["esq"], "d": tr["dir"], "v": val})
                      .groupby("uf").sum().pipe(lambda g: 100 * (g["e"] - g["d"]) / g["v"]))
    return anc, tr


def cenario(nd: Needle, tr: dict, p_pct: float, rho: float, lag_min: float, rng_u: np.ndarray):
    ordem = np.sort(tr["tempo"][tr["tem"]])
    t_p = ordem[max(0, int(len(ordem) * p_pct / 100) - 1)]
    return no_instante(nd, tr, t_p, rho, lag_min, rng_u)


def no_instante(nd: Needle, tr: dict, t_p, rho: float, lag_min: float, rng_u: np.ndarray):
    """O que o feed municipal e o crawler teriam visto no instante t_p (datetime64)."""
    t_p = np.datetime64(t_p)
    cont = tr["tem"] & (tr["tempo"] <= t_p)
    feed = None
    if cont.any():
        mc = nd.mun_cod[cont]
        f = {k: np.bincount(mc, tr[k][cont], nd.n_mun) for k in ["esq", "dir", "out", "bn"]}
        f["ea"] = np.bincount(mc, tr["apt"][cont], nd.n_mun)
        f["st"] = np.bincount(mc, minlength=nd.n_mun).astype(float)
        f["ts"] = nd.urnas_mun.astype(float)
        feed = pd.DataFrame(f)
        feed["uf"] = [k.split(":")[0] for k in nd.muns]
        feed["cd_mun"] = [int(k.split(":")[1]) for k in nd.muns]
        feed = feed[feed["st"] > 0]
    obs = None
    if rho > 0:
        lim = t_p - np.timedelta64(int(lag_min * 60), "s")
        cr = cont & (tr["tempo"] <= lim) & (rng_u < rho)
        idx = np.flatnonzero(cr)
        obs = {"idx": idx, **{k: tr[k][idx] for k in ["esq", "dir", "out", "bn"]}}
    return feed, obs, pd.Timestamp(t_p)


def roda(nd, tr, params: Params, rho=0.0, lag=0.0, marcos=MARCOS, rng_u=None, verbose=False):
    rng_u = rng_u if rng_u is not None else np.random.default_rng(7).random(nd.n)
    linhas = []
    for pp in marcos:
        feed, obs, hora = cenario(nd, tr, pp, rho, lag, rng_u)
        r = nd.estima(obs, feed, params)
        b = r["br"]
        e_uf = np.array([r["uf"][u]["margem"] - tr["final_uf"][u] for u in tr["final_uf"].index if u in r["uf"]])
        linhas.append({"pct": pp, "hora": hora.strftime("%H:%M"), "tela": b["tela_margem"],
                       "proj": b["margem"], "erro": b["margem"] - tr["final_margem"],
                       "erro_tela": (b["tela_margem"] - tr["final_margem"]) if b["tela_margem"] is not None else np.nan,
                       "uf_mae": float(np.abs(e_uf).mean()), "uf_max": float(np.abs(e_uf).max()),
                       "delta": b["delta_equiv"]})
    return pd.DataFrame(linhas)


def v1(marcos=MARCOS):
    df = monta_v1()
    final = 100 * float((df["v"] * df["m"]).sum() / df["v"].sum())
    out = {}
    for pp in marcos:
        n = max(2, int(len(df) * pp / 100))
        r = projeta_v1(df, n)
        out[pp] = r["modelo"] - final
    return out


def grava_sigma() -> int:
    """Incerteza por estagio: RMS do erro nacional nas duas noites de 2022 (T1, T2) x tres
    coberturas de boletim (0, 0,6 c/ 10 min de atraso, 1), com folga de 25% e piso.
    UF: erro absoluto medio entre UFs convertido em desvio (x sqrt(pi/2)). Provisorio:
    duas noites nao sao uma distribuicao -- o piso impede confianca espuria."""
    import json
    erros, ufs = {}, {}
    for turno in (1, 2):
        anc, tr = prepara(turno)
        nd = Needle(anc, turno=turno)
        for rho, lag in [(0.0, 0.0), (0.6, 10.0), (1.0, 0.0)]:
            t = roda(nd, tr, Params(), rho=rho, lag=lag)
            for _, r in t.iterrows():
                erros.setdefault(r["pct"], []).append(r["erro"])
                ufs.setdefault(r["pct"], []).append(r["uf_mae"])
    pcts = sorted(erros)
    sig_br = [max(0.5, 1.25 * float(np.sqrt(np.mean(np.square(erros[q]))))) for q in pcts]
    sig_uf = [max(0.8, 1.25 * float(np.mean(ufs[q])) * np.sqrt(np.pi / 2)) for q in pcts]
    # envoltoria conservadora: cada estagio leva o maior sigma dos estagios POSTERIORES
    # (a incerteza nao pode cair abaixo de um erro que ainda vai acontecer mais tarde)
    sig_br = list(np.maximum.accumulate(sig_br[::-1])[::-1])
    sig_uf = list(np.maximum.accumulate(sig_uf[::-1])[::-1])
    out = {"pct": [0.0] + pcts + [100.0], "sigma_br": [8.0] + sig_br + [0.05],
           "sigma_uf": [12.0] + sig_uf + [0.1],
           "fonte": "probe/calibra_hier.py --sigma (replay 2022 T1+T2, rho 0/0.6/1)"}
    (BASELINE / "calib_presidente.json").write_text(json.dumps(out, indent=1), "utf-8")
    for q, a_, b_ in zip(pcts, sig_br, sig_uf):
        print(f"  {q:5.2f}%  sigma BR {a_:5.2f}  sigma UF {b_:5.2f}")
    return 0


def main() -> int:
    a = sys.argv[1:]
    turno = 2 if "--t2" in a else 1
    anc, tr = prepara(turno)
    t0 = time.time()
    nd = Needle(anc, turno=turno)
    print(f"needle: {nd.n:,} urnas, {nd.n_mun:,} municipios, {nd.n_loc:,} locais  [{time.time() - t0:.1f}s]")
    print(f"final real: margem {tr['final_margem']:+.2f}")
    r0 = nd.estima(None, None)
    print(f"sem votos (= ancora): margem {r0['br']['margem']:+.2f}  dois-a-dois esq {100 * r0['br']['dois_esq']:.2f}%")

    if "--sigma" in a:
        return grava_sigma()
    if "--grade" in a:
        rhos = [0.0]
        grade = list(itertools.product([0.005, 0.02, 0.1], [5e3, 2e4, 1e5], [2e4, 1e5, 5e5],
                                       [100.0, 300.0, 1000.0]))
        res = []
        for L, K0, KUF, KMUN in grade:
            pr = Params(L=L, K0=K0, K_UF=KUF, K_MUN=KMUN)
            for rho in rhos:
                t = roda(nd, tr, pr, rho=rho, marcos=[0.5, 1, 2, 5, 10, 30])
                res.append({"L": L, "K0": K0, "K_UF": KUF, "K_MUN": KMUN, "rho": rho,
                            "mae_cedo": float(t.loc[t.pct <= 2, "erro"].abs().mean()),
                            "mae": float(t["erro"].abs().mean()),
                            "uf_mae_5": float(t.loc[t.pct == 5, "uf_mae"].iloc[0])})
        g = pd.DataFrame(res).sort_values("mae")
        print(g.head(15).round(3).to_string(index=False))
        g.to_csv(SAIDA / f"calib_hier_grade_t{turno}.csv", index=False)
        return 0

    rhos = [float(x) for x in a[a.index("--rho") + 1].split(",")] if "--rho" in a else [0.0, 0.5, 1.0]
    base = v1() if turno == 1 else {}
    p = Params()
    tabs = {}
    for rho in rhos:
        tabs[rho] = roda(nd, tr, p, rho=rho, lag=10.0 if 0 < rho < 1 else 0.0)
    t = tabs[rhos[0]][["pct", "hora", "tela", "erro_tela"]].copy()
    t["erro_v1"] = t["pct"].map(base) if base else np.nan
    for rho in rhos:
        t[f"erro_hier_rho{rho:g}"] = tabs[rho]["erro"]
        t[f"uf_mae_rho{rho:g}"] = tabs[rho]["uf_mae"]
    print(t.round(2).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
