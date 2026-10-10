"""Verificacao 2026: as tendencias demograficas que o sintetico esperava se confirmaram?

O sintetico fez duas apostas separadas, e cada uma tem o seu teste:

  COMPOSICAO  o eleitorado de 2026 e mais velho, um pouco mais escolarizado e mais
              evangelico; com os coeficientes de 2022, isso tira ~1,9 ponto de Lula nos
              validos a dois (projecao_2026.json).
  COMPORTAMENTO  cada grupo vota como votou em 2022 (coeficientes congelados).

Comparacao principal: 1o turno de 2026 contra o 1o turno de 2022 -- mesma natureza de
eleicao, terceiros presentes nos dois. (A ancora parte do 2o turno de 2022; o teste
limpo dela vem com o 2o turno de 2026, `--turno 2`.)

  1. Nivel: o 1o turno de 2022 andado pela demografia, contra o real.
  2. Composicao entre municipios: swing municipal real ~ deriva prevista (total e por
     eixo), com efeito fixo de UF -- o vento estadual (governador, candidato) nao e
     demografia. beta=1: a demografia andou o quanto o modelo previa; 0: nao apareceu.
  3. Composicao dentro do municipio: secoes pareadas 2022-2026, perfil REAL da secao nos
     dois anos (TSE), efeito fixo de municipio.
  4. Comportamento: o mesmo logit multinomial ajustado no 1o turno de 2022 e no de 2026,
     na mesma padronizacao (+1 dp de 2022) -- os contrastes Lula-direita mudaram?
  5. Onde o voto andou: swing real x previsto por UF, regiao, porte e quintis de
     cada eixo demografico.

Saida: sintetico/verificacao_2026.json (relatorio: sintetico.relatorio_verificacao)

Uso:  .venv/Scripts/python -m sintetico.verifica_2026 [--turno 1|2]
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np
import pandas as pd

from .caminhos import BASELINE, SAIDA, UF_REGIAO
from .modelo import EIXOS, monta_xy
from .projecao_2026 import PERFIL, deriva_2026

CHAVE = ["uf", "cd_mun", "zona", "secao"]
GRUPOS_DERIVA = {"idade": ["pct_1624", "pct_2539", "pct_60m"], "escolaridade": ["pct_fund", "pct_sup"],
                 "sexo": ["pct_fem"], "religiao": ["pct_evangelica", "pct_sem_religiao"]}
EIXOS_REG = ["idade", "escolaridade", "religiao"]
QUINTIS = {"pct_evangelica": "evangélicos (Censo, município)", "pct_sup": "ensino superior (eleitorado)",
           "pct_60m": "60 anos ou mais (eleitorado)", "pct_1624": "16 a 24 anos (eleitorado)",
           "renda_media": "renda do entorno do local", "pct_branca": "brancos (entorno do local)",
           "pct_rural": "rural (entorno do local)"}
PORTE = {5: "metrópole", 4: "capital regional", 3: "centro sub-regional", 2: "centro de zona",
         1: "centro local"}


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sig(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def pp(x):
    return round(100 * float(x), 2)


# ----------------------------------------------------------------------------- dados

def resultado(ano: int, turno: int) -> pd.DataFrame:
    """Presidente por secao: esq, dir, outros, brancos+nulos, aptos (sem exterior)."""
    p = pd.read_parquet(BASELINE / f"presidente_secao_{ano}.parquet")
    p["cd_mun"] = p["cd_municipio"].astype(int)
    t = f"t{turno}_"
    out = pd.DataFrame({**{k: p[k] for k in CHAVE},
                        "esq": p[t + "esq"], "dir": p[t + "dir"],
                        "outros": p["t1_outros"] if turno == 1 else 0,
                        "bn": p[t + "branco"] + p[t + "nulo"]})
    if ano == 2022:
        a = pd.read_parquet(BASELINE / f"carimbos_presidente_2022_t{turno}.parquet",
                            columns=["uf", "cd_municipio", "zona", "secao", "aptos"])
    else:
        a = pd.read_parquet(BASELINE / f"detalhe_secao_{ano}.parquet",
                            columns=["uf", "cd_municipio", "zona", "secao", "cargo", "turno", "aptos"])
        a = a[(a["cargo"] == "PRESIDENTE") & (a["turno"] == str(turno))]
    a["cd_mun"] = a["cd_municipio"].astype(int)
    a = a.groupby(CHAVE, as_index=False)["aptos"].sum()
    out = out.merge(a, on=CHAVE, how="left")
    out = out[(out["uf"] != "ZZ") & (out["esq"] + out["dir"] > 0)].copy()
    out["aptos"] = out["aptos"].fillna(out["esq"] + out["dir"] + out["outros"] + out["bn"])
    return out


def q_de(esq, dir_):
    return (np.asarray(esq, float) + .5) / (np.asarray(esq, float) + np.asarray(dir_, float) + 1)


def perfil_2026_principal() -> pd.DataFrame:
    """Perfil TSE de 2026 somado na urna principal (secoes agregadas votam nela)."""
    pf = pd.read_parquet(SAIDA / "perfil_secao_2026.parquet").rename(columns={"cd_municipio_tse": "cd_mun"})
    u = pd.read_parquet(SAIDA / "universo_2026.parquet", columns=CHAVE + ["secao_principal"])
    pf = pf.merge(u, on=CHAVE, how="left")
    pf["secao"] = np.where(pf["secao_principal"] > 0, pf["secao_principal"], pf["secao"])
    w = pf["eleitores"].astype(float)
    num = pf[PERFIL].mul(w, axis=0).groupby([pf[k] for k in CHAVE]).sum()
    den = w.groupby([pf[k] for k in CHAVE]).sum()
    return num.div(den, axis=0).reset_index()


# ----------------------------------------------------------------------------- modelo

class Sintetico:
    def __init__(self, M: dict):
        self.M = M
        self.coef, self.inter = np.array(M["coef"]), np.array(M["intercept"])

    def xz(self, df: pd.DataFrame) -> np.ndarray:
        return monta_xy(df, self.M["mu"], self.M["sd"])[0]

    def probs(self, Xz: np.ndarray, coef=None, inter=None) -> np.ndarray:
        eta = Xz @ (self.coef if coef is None else coef).T + (self.inter if inter is None else inter)
        eta -= eta.max(1, keepdims=True)
        p = np.exp(eta)
        return p / p.sum(1, keepdims=True)


def esq_dois(p: np.ndarray, w: np.ndarray) -> float:
    return float((p[:, 0] * w).sum() / ((p[:, 0] + p[:, 1]) * w).sum())


def q_agregado(p: np.ndarray, w: np.ndarray, grupo) -> pd.Series:
    d = pd.DataFrame({"l": p[:, 0] * w, "d": (p[:, 0] + p[:, 1]) * w, "g": grupo})
    s = d.groupby("g")[["l", "d"]].sum()
    return s["l"] / s["d"]


class Multinomial:
    """Logit multinomial agrupado (contagens por secao), MLE por L-BFGS sem replicar linhas.
    Mesmo modelo de modelo.ajusta (sem penalidade), com a classe 'nenhum' como referencia:
    os contrastes entre classes sao identicos aos do sklearn, e a memoria cabe na maquina."""

    def __init__(self, X: np.ndarray, C: np.ndarray):
        from scipy.optimize import minimize
        n, k = X.shape
        X1 = np.c_[X, np.ones(n)]
        N = C.sum(1)
        tot = C.sum()

        def f(w):
            W = np.zeros((3, k + 1))
            W[:2] = w.reshape(2, k + 1)
            eta = X1 @ W.T
            eta -= eta.max(1, keepdims=True)
            lse = np.log(np.exp(eta).sum(1))
            ll = (C * (eta - lse[:, None])).sum()
            P = np.exp(eta - lse[:, None])
            g = -(X1.T @ (C[:, :2] - N[:, None] * P[:, :2])).T
            return -ll / tot, g.ravel() / tot

        r = minimize(f, np.zeros(2 * (k + 1)), jac=True, method="L-BFGS-B",
                     options={"maxiter": 2000, "gtol": 1e-9})
        W = np.zeros((3, k + 1))
        W[:2] = r.x.reshape(2, k + 1)
        self.coef_, self.intercept_ = W[:, :k], W[:, k]
        self.convergiu = bool(r.success)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        eta = X @ self.coef_.T + self.intercept_
        eta -= eta.max(1, keepdims=True)
        p = np.exp(eta)
        return p / p.sum(1, keepdims=True)


# ----------------------------------------------------------------------------- regressao

def demean(M: np.ndarray, w: np.ndarray, g) -> np.ndarray:
    codes, _ = pd.factorize(g)
    W = np.bincount(codes, weights=w)
    out = np.empty_like(M, dtype=float)
    for j in range(M.shape[1]):
        out[:, j] = M[:, j] - (np.bincount(codes, weights=w * M[:, j]) / W)[codes]
    return out


def wls(y, X, w, fe=None, cluster=None, nomes=None) -> dict:
    """MQP com efeito fixo (within) e erro-padrao robusto por cluster."""
    X = np.atleast_2d(np.asarray(X, float).T).T
    y = np.asarray(y, float)
    w = np.asarray(w, float)
    if fe is not None:
        Z = demean(np.column_stack([y, X]), w, fe)
        y_, X_ = Z[:, 0], Z[:, 1:]
    else:
        X_ = np.column_stack([np.ones(len(y)), X])
        y_ = y - np.average(y, weights=w) * 0
    sw = np.sqrt(w)
    Xw, yw = X_ * sw[:, None], y_ * sw
    A = np.linalg.pinv(Xw.T @ Xw)
    b = A @ Xw.T @ yw
    e = yw - Xw @ b
    codes, _ = pd.factorize(cluster if cluster is not None else np.arange(len(y)))
    G = np.zeros((codes.max() + 1, Xw.shape[1]))
    np.add.at(G, codes, Xw * e[:, None])
    se = np.sqrt(np.diag(A @ (G.T @ G) @ A))
    if fe is None:
        b, se = b[1:], se[1:]
        ym = np.average(y, weights=w)
        tss = float((w * (y - ym) ** 2).sum())
    else:
        tss = float((w * y_ ** 2).sum())
    nomes = nomes or [f"x{i}" for i in range(len(b))]
    return {"coef": {n: round(float(v), 5) for n, v in zip(nomes, b)},
            "ep": {n: round(float(v), 5) for n, v in zip(nomes, se)},
            "r2": round(1 - float((e ** 2).sum()) / tss, 3), "n": int(len(y)),
            "clusters": int(codes.max() + 1)}


# ----------------------------------------------------------------------------- analise

def main() -> int:
    turno = int(sys.argv[sys.argv.index("--turno") + 1]) if "--turno" in sys.argv else 1
    t0 = time.time()
    M22 = json.loads((SAIDA / "modelo_2022.json").read_text("utf-8"))
    sint = Sintetico(M22)
    proj_json = json.loads((SAIDA / "projecao_2026.json").read_text("utf-8"))

    r22, r26 = resultado(2022, turno), resultado(2026, turno)
    r22t2 = resultado(2022, 2) if turno == 1 else None
    print(f"secoes: 2022 {len(r22):,}  2026 {len(r26):,}  [{time.time() - t0:.0f}s]", flush=True)

    # --- base 2022 (covariaveis) e deriva demografica, com cada eixo isolado
    base = pd.read_parquet(SAIDA / "base_2022.parquet").drop(columns=["cd_mun"]) \
        .rename(columns={"cd_municipio_tse": "cd_mun"})
    rel10 = pd.read_parquet(SAIDA / "religiao_2010.parquet")
    proj, _, _, _ = deriva_2026(base.rename(columns={"cd_mun": "cd_municipio_tse"}), rel10)
    proj = proj.rename(columns={"cd_municipio_tse": "cd_mun"})
    X22 = sint.xz(base)
    p22 = sint.probs(X22)
    cols = M22["cols"]
    # uma variante por vez: a maquina nao tem RAM para cinco copias da base
    pv = {"total": sint.probs(sint.xz(proj))}
    for g, gcols in GRUPOS_DERIVA.items():
        guarda = base[gcols].copy()
        base[gcols] = proj[gcols].to_numpy()
        pv[g] = sint.probs(sint.xz(base))
        base[gcols] = guarda
    del proj
    drift_sec = logit(pv["total"][:, 0] / pv["total"][:, :2].sum(1)) - logit(p22[:, 0] / p22[:, :2].sum(1))

    # --- 1. nivel
    b = base[CHAVE].copy()
    b["drift"] = drift_sec
    m = r22.merge(b, on=CHAVE, how="left")
    m["drift"] = m["drift"].fillna(np.average(drift_sec, weights=base["aptos"]))
    w22 = (m["esq"] + m["dir"]).to_numpy(float)
    q22 = q_de(m["esq"], m["dir"])
    andado = float((w22 * sig(logit(q22) + m["drift"])).sum() / w22.sum())
    real22 = float(r22["esq"].sum() / (r22["esq"] + r22["dir"]).sum())
    real26 = float(r26["esq"].sum() / (r26["esq"] + r26["dir"]).sum())
    val26 = (r26["esq"] + r26["dir"] + r26["outros"]).sum()
    # vento: deslocamento uniforme (log-odds, direita +) que leva o andado ao real
    lo, hi = -1.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        v = float((w22 * sig(logit(q22) + m["drift"] - mid)).sum() / w22.sum())
        lo, hi = (mid, hi) if v > real26 else (lo, mid)
    vento = (lo + hi) / 2
    nivel = {
        "turno": turno,
        "real_2022": pp(real22), "real_2026": pp(real26),
        "real_2022_t2": pp(r22t2["esq"].sum() / (r22t2["esq"] + r22t2["dir"]).sum()) if r22t2 is not None else None,
        "andado_demografia": pp(andado),
        "efeito_demografia_pp": pp(andado - real22),
        "mudanca_real_pp": pp(real26 - real22),
        "resto_pp": pp(real26 - andado),
        "vento_logodds_direita": round(vento, 3),
        "sintetico_t2": {"base_2022": pp(proj_json["base_2022"]["validos_esq"]),
                         "proj_2026": pp(proj_json["proj_2026"]["validos_esq"]),
                         "so_eleitorado": pp(proj_json["so_eleitorado"]["validos_esq"]),
                         "so_religiao": pp(proj_json["so_religiao"]["validos_esq"])},
        "validos_2026": {"esq": pp(r26["esq"].sum() / val26), "dir": pp(r26["dir"].sum() / val26),
                         "outros": pp(r26["outros"].sum() / val26)},
        "comparecimento": {"2022": pp(1 - (r22["aptos"] - r22[["esq", "dir", "outros", "bn"]].sum(1)).sum() / r22["aptos"].sum()),
                           "2026": pp(1 - (r26["aptos"] - r26[["esq", "dir", "outros", "bn"]].sum(1)).sum() / r26["aptos"].sum())},
    }
    print(f"nivel: 2022 {nivel['real_2022']}  andado {nivel['andado_demografia']}  real 2026 "
          f"{nivel['real_2026']}  (demografia {nivel['efeito_demografia_pp']:+}, resto {nivel['resto_pp']:+}, "
          f"vento {vento:+.3f})", flush=True)

    # --- 2. composicao entre municipios
    w_apt = base["aptos"].to_numpy(float)
    qm22 = q_agregado(p22, w_apt, base["cd_mun"])
    dm = pd.DataFrame({g: pd.Series(logit(q_agregado(pv[g], w_apt, base["cd_mun"])) - logit(qm22), index=qm22.index)
                       for g in pv})
    mun22 = r22.groupby("cd_mun")[["esq", "dir"]].sum()
    mun26 = r26.groupby(["uf", "cd_mun"])[["esq", "dir"]].sum().reset_index().set_index("cd_mun")
    mun = mun26.join(mun22, lsuffix="26", rsuffix="22", how="inner").join(dm, how="inner")
    mun["swing"] = logit(q_de(mun["esq26"], mun["dir26"])) - logit(q_de(mun["esq22"], mun["dir22"]))
    wm = (mun["esq26"] + mun["dir26"]).to_numpy(float)
    comp_mun = {
        "n_municipios": int(len(mun)),
        "total_sem_fe": wls(mun["swing"], mun["total"], wm, cluster=mun["uf"], nomes=["deriva"]),
        "total_fe_uf": wls(mun["swing"], mun["total"], wm, fe=mun["uf"], cluster=mun["uf"], nomes=["deriva"]),
        # sexo fica de fora: a deriva prevista quase nao varia entre municipios (coeficiente explode)
        "eixos_fe_uf": wls(mun["swing"], mun[EIXOS_REG].to_numpy(), wm, fe=mun["uf"],
                           cluster=mun["uf"], nomes=EIXOS_REG),
        "dp_deriva": {g: round(float(np.sqrt(np.cov(mun[g], aweights=wm))), 4) for g in ["total", *GRUPOS_DERIVA]},
        "dp_swing": round(float(np.sqrt(np.cov(mun["swing"], aweights=wm))), 4),
    }
    print(f"municipios: beta deriva (FE UF) = {comp_mun['total_fe_uf']['coef']['deriva']} "
          f"(ep {comp_mun['total_fe_uf']['ep']['deriva']}); eixos {comp_mun['eixos_fe_uf']['coef']}", flush=True)

    # --- 3. composicao dentro do municipio (secoes pareadas, perfil real nos dois anos)
    pf26 = perfil_2026_principal()
    par = base[CHAVE + ["aptos"]].reset_index().merge(pf26, on=CHAVE, how="inner", suffixes=("", "_26"))
    ix = par["index"].to_numpy()
    Xp = X22[ix].copy()                     # perfil REAL de 2026 da secao, o resto como em 2022
    for c in PERFIL:
        j = cols.index(c)
        z = ((par[c] - M22["mu"][j]) / M22["sd"][j]).to_numpy()
        Xp[:, j] = np.where(np.isnan(z), Xp[:, j], z)
    p_par22 = p22[ix]
    p_par26 = sint.probs(Xp)
    del Xp
    par["d_perfil"] = logit(p_par26[:, 0] / p_par26[:, :2].sum(1)) - logit(p_par22[:, 0] / p_par22[:, :2].sum(1))
    for c in ["pct_60m", "pct_sup", "pct_1624"]:
        par[f"delta_{c}"] = par[c].to_numpy() - base.loc[par["index"], c].to_numpy()
    par = par.drop(columns=PERFIL).merge(r22[CHAVE + ["esq", "dir", "aptos"]], on=CHAVE, suffixes=("", "_r22")) \
        .merge(r26[CHAVE + ["esq", "dir", "aptos"]], on=CHAVE, suffixes=("22", "26"))
    razao = par["aptos26"] / par["aptos22"].clip(lower=1)
    estavel = par[(razao.between(0.85, 1.15)) & (par["esq22"] + par["dir22"] >= 50)
                  & (par["esq26"] + par["dir26"] >= 50)].copy()
    estavel["swing"] = logit(q_de(estavel["esq26"], estavel["dir26"])) - logit(q_de(estavel["esq22"], estavel["dir22"]))
    ws = (estavel["esq26"] + estavel["dir26"]).to_numpy(float)
    comp_sec = {
        "pareadas": int(len(par)), "estaveis": int(len(estavel)),
        "aptos_estaveis_pct": pp(estavel["aptos26"].sum() / r26["aptos"].sum()),
        "fe_municipio": wls(estavel["swing"], estavel["d_perfil"], ws, fe=estavel["cd_mun"],
                            cluster=estavel["cd_mun"], nomes=["deriva_perfil"]),
        "deltas_fe_municipio": wls(estavel["swing"],
                                   estavel[["delta_pct_60m", "delta_pct_sup", "delta_pct_1624"]].to_numpy() * 100,
                                   ws, fe=estavel["cd_mun"], cluster=estavel["cd_mun"],
                                   nomes=["60+ (por pp)", "superior (por pp)", "16-24 (por pp)"]),
        "dp_deriva_perfil": round(float(np.sqrt(np.cov(estavel["d_perfil"], aweights=ws))), 4),
    }
    # efeito esperado de +1 pp em cada eixo, em log-odds Lula/direita, pelos coeficientes de 2022
    contraste = np.array(M22["coef"])[0] - np.array(M22["coef"])[1]
    comp_sec["esperado_por_pp"] = {rot: round(float(contraste[cols.index(c)] / M22["sd"][cols.index(c)] * 0.01), 4)
                                   for rot, c in [("60+ (por pp)", "pct_60m"), ("superior (por pp)", "pct_sup"),
                                                  ("16-24 (por pp)", "pct_1624")]}
    print(f"secoes estaveis: {len(estavel):,}  beta deriva perfil (FE mun) = "
          f"{comp_sec['fe_municipio']['coef']['deriva_perfil']} (ep {comp_sec['fe_municipio']['ep']['deriva_perfil']})",
          flush=True)

    # --- 4. comportamento: mesmo modelo no 1o turno de 2022 e de 2026
    cnt = base[CHAVE].merge(r22[CHAVE + ["esq", "dir", "aptos"]], on=CHAVE, how="left")   # ordem da base
    ok = cnt["esq"].notna().to_numpy()
    cnt = cnt[ok]
    Xa = X22[ok]
    Ca = np.c_[cnt["esq"], cnt["dir"], np.maximum(cnt["aptos"] - cnt["esq"] - cnt["dir"], 0)].astype(float)
    m22 = Multinomial(Xa, Ca)

    anc = pd.read_parquet(SAIDA / "ancora_2026.parquet")
    xc = [f"x_{c}" for c in cols]
    anc = anc[CHAVE + xc].merge(pf26, on=CHAVE, how="left")
    for c in PERFIL:
        j = cols.index(c)
        z = (anc[c] - M22["mu"][j]) / M22["sd"][j]
        anc[f"x_{c}"] = z.fillna(anc[f"x_{c}"])
    b26 = anc.merge(r26[CHAVE + ["esq", "dir", "aptos"]], on=CHAVE)
    Xb = b26[xc].to_numpy(float)
    Cb = np.c_[b26["esq"], b26["dir"], np.maximum(b26["aptos"] - b26["esq"] - b26["dir"], 0)].astype(float)
    m26 = Multinomial(Xb, Cb)

    def contr(m):
        return m.coef_[0] - m.coef_[1]
    c22, c26 = contr(m22), contr(m26)
    hist = json.loads((SAIDA / "comparativo.json").read_text("utf-8"))["deriva"]
    comportamento = {"contrastes": [
        {"col": c, "eixo": next(e for e, cs in EIXOS.items() if c in cs),
         "t1_2022": round(float(c22[i]), 3), "t1_2026": round(float(c26[i]), 3),
         "mudanca": round(float(c26[i] - c22[i]), 3),
         "t2_hist": {a: round(v, 3) for a, v in hist[c].items()}}
        for i, c in enumerate(cols)]}
    # decomposicao nacional: composicao (coef 2022 T1, demografia 2026) x comportamento
    pa22 = m22.predict_proba(Xa)
    pa22_x26 = m22.predict_proba(Xb)
    pb26 = m26.predict_proba(Xb)
    wa, wb = Ca.sum(1), Cb.sum(1)
    comportamento["decomposicao"] = {
        "t1_2022_modelo": pp(esq_dois(pa22, wa)),
        "coef22_demografia26": pp(esq_dois(pa22_x26, wb)),
        "t1_2026_modelo": pp(esq_dois(pb26, wb)),
    }
    # quanto do swing entre secoes cada mudanca de coeficiente explica (so inclinacoes)
    eta22 = Xb @ m22.coef_.T + m22.intercept_
    contrib = {}
    for eixo, ecols in EIXOS.items():
        idx = [cols.index(c) for c in ecols]
        d = (Xb[:, idx] @ (m26.coef_[:, idx] - m22.coef_[:, idx]).T)
        delta_lo = (eta22[:, 0] + d[:, 0]) - (eta22[:, 1] + d[:, 1]) - (eta22[:, 0] - eta22[:, 1])
        contrib[eixo] = round(float(np.sqrt(np.cov(delta_lo, aweights=wb))), 4)
    comportamento["dp_swing_por_eixo"] = contrib
    print(f"comportamento: decomposicao {comportamento['decomposicao']}", flush=True)

    # --- 5. onde o voto andou: UF, regiao, porte e quintis
    def tabela(grupo22, grupo26, rot) -> list[dict]:
        g22 = m.assign(g=grupo22, w=w22, q=q22, qa=sig(logit(q22) + m["drift"]))
        a22 = g22.groupby("g").apply(lambda d: pd.Series({
            "q22": np.average(d["q"], weights=d["w"]), "andado": np.average(d["qa"], weights=d["w"])}),
            include_groups=False)
        g26 = r26.assign(g=grupo26).groupby("g")[["esq", "dir"]].sum()
        a26 = g26["esq"] / (g26["esq"] + g26["dir"])
        out = []
        for k in a22.index.intersection(a26.index):
            out.append({rot: str(k), "q22": pp(a22.loc[k, "q22"]), "andado": pp(a22.loc[k, "andado"]),
                        "q26": pp(a26.loc[k]), "previsto_pp": pp(a22.loc[k, "andado"] - a22.loc[k, "q22"]),
                        "real_pp": pp(a26.loc[k] - a22.loc[k, "q22"]),
                        "votos26": int(g26.loc[k].sum())})
        return out

    por_uf = tabela(m["uf"], r26["uf"], "uf")
    por_regiao = tabela(m["uf"].map(UF_REGIAO), r26["uf"].map(UF_REGIAO), "regiao")
    hier = base.groupby("cd_mun")["hierarquia_num"].first()
    por_porte = tabela(m["cd_mun"].map(hier).map(PORTE), r26["cd_mun"].map(hier).map(PORTE), "porte")

    # quintis: secoes estaveis (mesmo lugar nos dois anos), covariavel de 2022
    est = estavel.merge(base[CHAVE + list(QUINTIS)], on=CHAVE).merge(b, on=CHAVE)
    wq = (est["esq22"] + est["dir22"]).to_numpy(float)
    quintis = {}
    for c, rot in QUINTIS.items():
        ok = est[c].notna().to_numpy()
        e = est[ok]
        ordem = np.argsort(e[c].to_numpy())
        cum = np.cumsum(wq[ok][ordem]) / wq[ok].sum()
        qt = np.empty(len(e), int)
        qt[ordem] = np.minimum((cum * 5).astype(int), 4)
        linhas = []
        for k in range(5):
            s = e[qt == k]
            w0 = (s["esq22"] + s["dir22"]).to_numpy(float)
            q0 = q_de(s["esq22"], s["dir22"])
            qa = float((w0 * sig(logit(q0) + s["drift"])).sum() / w0.sum())
            r0 = float(s["esq22"].sum() / (s["esq22"] + s["dir22"]).sum())
            r1 = float(s["esq26"].sum() / (s["esq26"] + s["dir26"]).sum())
            linhas.append({"quintil": k + 1, "faixa": [round(float(s[c].min()), 3), round(float(s[c].max()), 3)],
                           "q22": pp(r0), "q26": pp(r1), "previsto_pp": pp(qa - r0), "real_pp": pp(r1 - r0)})
        quintis[c] = {"rotulo": rot, "linhas": linhas}

    saida = {"gerado_em": time.strftime("%Y-%m-%d %H:%M"), "nivel": nivel,
             "composicao_municipios": comp_mun, "composicao_secoes": comp_sec,
             "comportamento": comportamento, "por_uf": por_uf, "por_regiao": por_regiao,
             "por_porte": por_porte, "quintis": quintis}
    nome = f"verificacao_2026{'' if turno == 1 else '_t2'}.json"
    (SAIDA / nome).write_text(json.dumps(saida, ensure_ascii=False, indent=1), "utf-8")
    print(f"gravado {nome} [{time.time() - t0:.0f}s]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
