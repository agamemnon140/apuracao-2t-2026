"""As eleicoes MUNICIPAIS turbinam a previsao da eleicao geral seguinte?

2020 -> 2022 e o analogo exato de 2024 -> 2026. Duas frentes:

GOVERNADOR — covariavel POR CANDIDATO: o share do partido dele no voto de vereador de 2020,
secao a secao (fallback: municipio; fallback: estado). A hipotese e que a capilaridade
municipal do partido diz onde o candidato vai bem antes de a apuracao chegar la.

PRESIDENTE — covariavel unica: share do bloco de esquerda no vereador 2020 por secao,
somada ao eixo de 2018 na mesma regressao ridge.

Comparacao honesta: mesmo modelo, mesmos marcos, com e sem a covariavel nova.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.modelo import monta as monta_pres, projeta as proj_pres
from pipeline.modelo_estadual import BASE, CHAVE, K_B, K_MUN, eixo_2018

ESQUERDA = {"13", "12", "40", "50", "65", "43", "18"}
MARCOS = [1, 2, 3, 5, 10, 20]


def shares_2020():
    v = pd.read_parquet(BASE / "vereador_partido_secao_2020_t1.parquet")
    tot_sec = v.groupby(CHAVE)["votos"].transform("sum")
    v = v.assign(sh=v["votos"] / tot_sec)
    mun = (v.groupby(["uf", "cd_municipio", "partido"])["votos"].sum()
           / v.groupby(["uf", "cd_municipio"])["votos"].sum()).rename("sh_mun").reset_index()
    ufp = (v.groupby(["uf", "partido"])["votos"].sum()
           / v.groupby("uf")["votos"].sum()).rename("sh_uf").reset_index()
    esq = (v[v["partido"].isin(ESQUERDA)].groupby(CHAVE)["votos"].sum()
           / v.groupby(CHAVE)["votos"].sum()).rename("esq20").reset_index()
    return v[CHAVE + ["partido", "sh"]], mun, ufp, esq


def monta_gov_nr(uf, car):
    """Governador pivotado por NR (numero de partido) — o elo com o vereador 2020."""
    g = pd.read_parquet(BASE / "governador_secao_2022_t1.parquet")
    g = g[(g["uf"] == uf) & g["candidato"]]
    wide = g.pivot_table(index=CHAVE, columns="nr_votavel", values="votos",
                         aggfunc="sum", fill_value=0).reset_index()
    sec = car[car["uf"] == uf][CHAVE + ["aptos", "prim_tot"]].merge(wide, on=CHAVE, how="inner")
    sec = sec.merge(eixo_2018(), on=CHAVE, how="left")
    med = (sec.dropna(subset=["z"]).groupby("cd_municipio")
           .apply(lambda x: np.average(x["z"], weights=x["peso18"]), include_groups=False)
           .rename("fb").reset_index())
    sec = sec.merge(med, on="cd_municipio", how="left")
    sec["z"] = sec["z"].fillna(sec["fb"]).fillna(sec["z"].mean())
    cands = [c for c in wide.columns if c not in CHAVE]
    sec["validos"] = sec[cands].sum(axis=1)
    return sec[sec["validos"] > 0].sort_values("prim_tot").reset_index(drop=True), cands


def anexa_x(sec, cands, sh_sec, sh_mun, sh_uf, uf):
    """Coluna x_{nr} por secao: share do partido nr no vereador 2020."""
    for nr in cands:
        s = sh_sec[sh_sec["partido"] == nr][CHAVE + ["sh"]]
        sec = sec.merge(s.rename(columns={"sh": f"x_{nr}"}), on=CHAVE, how="left")
        m = sh_mun[(sh_mun["uf"] == uf) & (sh_mun["partido"] == nr)][["cd_municipio", "sh_mun"]]
        sec = sec.merge(m, on="cd_municipio", how="left")
        u = sh_uf[(sh_uf["uf"] == uf) & (sh_uf["partido"] == nr)]["sh_uf"]
        sec[f"x_{nr}"] = sec[f"x_{nr}"].fillna(sec["sh_mun"]).fillna(
            float(u.iloc[0]) if len(u) else 0.0)
        sec = sec.drop(columns="sh_mun")
    return sec


def projeta3(sec, cands, n, com_x):
    """Ridge por candidato com [z] ou [z, x_c] + efeito de municipio (a producao)."""
    w = sec["validos"].to_numpy(float)[:n]
    if w.sum() <= 0:
        return pd.Series(dtype=float)
    z = sec["z"].to_numpy()
    cod, uniq = pd.factorize(sec["cd_municipio"])
    m_ap, m_f, nmun = cod[:n], cod[n:], len(uniq)
    taxa = w.sum() / sec["aptos"].to_numpy()[:n].sum()
    v_f = sec["aptos"].to_numpy(float)[n:] * taxa
    out = {}
    for c in cands:
        y = sec[c].to_numpy(float)[:n] / w
        cols = [z[:n]] + ([sec[f"x_{c}"].to_numpy()[:n]] if com_x else [])
        X = np.column_stack(cols)
        xb = np.average(X, axis=0, weights=w)
        Xc = X - xb
        yb = float(np.average(y, weights=w))
        A = (Xc * w[:, None]).T @ Xc
        b = (Xc * w[:, None]).T @ (y - yb)
        kd = [K_B * float(sec["validos"].sum() * sec["z"].var())]
        if com_x:
            kd.append(K_B * float(sec["validos"].sum() * max(sec[f"x_{c}"].var(), 1e-6)))
        coef = np.linalg.solve(A + np.diag(kd), b)
        colsf = [z[n:]] + ([sec[f"x_{c}"].to_numpy()[n:]] if com_x else [])
        y_f = yb + (np.column_stack(colsf) - xb) @ coef
        r = y - (yb + Xc @ coef)
        num = np.bincount(m_ap, weights=w * r, minlength=nmun)
        den = np.bincount(m_ap, weights=w, minlength=nmun) + K_MUN
        out[c] = float((w * y).sum() + (v_f * np.clip(y_f + (num / den)[m_f], 0, 1)).sum())
    s = pd.Series(out)
    return s / s.sum()


def main() -> None:
    sh_sec, sh_mun, sh_uf, esq = shares_2020()
    car = pd.read_parquet(BASE / "carimbos_governador_2022_t1.parquet")
    ufs = sorted(car["uf"].unique())

    print("=== GOVERNADOR: base (z+municipio) x +vereador2020 do partido ===", flush=True)
    res = []
    for uf in ufs:
        sec, cands = monta_gov_nr(uf, car)
        sec = anexa_x(sec, cands, sh_sec, sh_mun, sh_uf, uf)
        final = sec[cands].sum() / sec[cands].sum().sum()
        o = final.sort_values(ascending=False)
        camp, dupla = o.index[0], set(o.index[:2])
        for p in MARCOS:
            n = max(5, int(len(sec) * p / 100))
            for rot, cx in (("base", False), ("+2020", True)):
                pr = projeta3(sec, cands, n, cx)
                po = pr.sort_values(ascending=False)
                res.append({"uf": uf, "p": p, "m": rot,
                            "err": 100 * abs(pr[camp] - final[camp]),
                            "dupla": set(po.index[:2]) == dupla})
        print(f"  {uf} ok", flush=True)
    d = pd.DataFrame(res)
    for titulo, campo, agg in (("erro mediano do lider", "err", "median"),
                               ("pior erro", "err", "max"), ("dupla certa %", "dupla", "mean")):
        piv = d.pivot_table(index="p", columns="m", values=campo, aggfunc=agg)
        if campo == "dupla":
            piv = piv.mul(100)
        print(f"\n{titulo}")
        print(piv[["base", "+2020"]].round(2).to_string())

    print("\n=== PRESIDENTE: eixo 2018 x eixo 2018 + esquerda no vereador 2020 ===", flush=True)
    df = monta_pres()
    df = df.merge(esq, on=CHAVE, how="left")
    med = df.groupby(["uf", "cd_municipio"])["esq20"].transform("mean")
    df["s"] = df["esq20"].fillna(med).fillna(df["esq20"].mean())   # entra no slot com_tamanho
    final = 100 * float((df["v"] * df["m"]).sum() / df["v"].sum())
    print("  apurado |   so eixo   |  +vereador2020")
    for p in MARCOS:
        n = max(2, int(len(df) * p / 100))
        r0 = proj_pres(df, n, com_tamanho=False)
        r1 = proj_pres(df, n, com_tamanho=True)
        print(f"  {p:5.1f}%  |  {r0['modelo']-final:+7.2f}   |  {r1['modelo']-final:+7.2f}")


if __name__ == "__main__":
    main()
