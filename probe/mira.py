"""Se so da para coletar secao em ALGUMAS cidades, quais?

A camada de secao inteira custa ~472 mil requisicoes por ciclo. Este teste pergunta se ha um
subconjunto que compra a maior parte do ganho -- e por qual criterio escolhe-lo. Tudo o que
entra no criterio e conhecido ANTES da eleicao (vem de 2018):

  H       heterogeneidade interna da cidade  -> gera ruido no parcial
  rho     ordem de chegada politicamente correlacionada -> gera vies sistematico
  dano    H x rho x eleitorado -> o estrago esperado daquela cidade no total do estado

Fundo de comparacao: municipio ja corrigido pela curva de chegada historica (custo zero).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.modelo_estadual import BASE, K_B, K_MUN, monta
from probe.ordem_historica import GRADE, curvas_2018

ORCAMENTOS = [0, 5_000, 25_000, 100_000, 200_000, 10**9]
CRITERIOS = ["dano", "H", "aptos"]
MARCOS = [3, 5, 10, 20]


def projeta(sec, cands, n, finas: set, curvas) -> pd.Series:
    w = sec["validos"].to_numpy(float)[:n]
    if w.sum() <= 0:
        return pd.Series(dtype=float)
    z_todos = sec["z"].to_numpy(); aptos = sec["aptos"].to_numpy(float)
    cod, uniq = pd.factorize(sec["cd_municipio"])
    nmun = len(uniq); m_ap, m_f = cod[:n], cod[n:]
    z_mun = (np.bincount(cod, weights=aptos * z_todos, minlength=nmun)
             / np.bincount(cod, weights=aptos, minlength=nmun))

    # municipio corrigido pela curva historica (fundo)
    ap_m = np.bincount(m_ap, weights=aptos[:n], minlength=nmun)
    tot_m = np.bincount(cod, weights=aptos, minlength=nmun)
    frac = np.clip(ap_m / np.maximum(tot_m, 1e-9), 0.01, 1.0)
    z_est = z_mun.copy()
    for i, cd in enumerate(uniq):
        c = curvas.get(cd)
        if c is not None:
            z_est[i] = z_mun[i] + (np.interp(frac[i], GRADE, c) - c[-1])

    fina = np.isin(uniq, list(finas))
    z_obs = np.where(fina[m_ap], z_todos[:n], z_est[m_ap])

    zb = float(np.average(z_obs, weights=w)); szz = float((w * (z_obs - zb) ** 2).sum())
    k = K_B * float(sec["validos"].sum() * sec["z"].var())
    taxa = w.sum() / aptos[:n].sum(); v_f = aptos[n:] * taxa
    out = {}
    for c in cands:
        y = sec[c].to_numpy(float)[:n] / w; yb = float(np.average(y, weights=w))
        b = float((w * (z_obs - zb) * (y - yb)).sum()) / (szz + k) if (szz + k) > 0 else 0.0
        a_ = yb - b * zb
        r = y - (a_ + b * z_obs)
        num = np.bincount(m_ap, weights=w * r, minlength=nmun)
        den = np.bincount(m_ap, weights=w, minlength=nmun) + K_MUN
        out[c] = float((w * y).sum() + (v_f * np.clip(a_ + b * z_todos[n:] + (num / den)[m_f], 0, 1)).sum())
    s = pd.Series(out)
    return s / s.sum()


def main() -> None:
    P = pd.read_parquet(BASE / "perfil_municipio_2018.parquet")
    curvas = curvas_2018()
    ufs = sorted(pd.read_parquet(BASE / "governador_secao_2022_t1.parquet")["uf"].unique())
    dados = {uf: monta(uf) for uf in ufs}

    selecoes = {}
    for crit in CRITERIOS:
        ordenado = P.sort_values(crit, ascending=False)
        acum = ordenado["secoes"].cumsum()
        for orc in ORCAMENTOS:
            sel = set(ordenado.loc[acum <= orc, "cd_municipio"]) if orc < 10**9 else set(P["cd_municipio"])
            selecoes[(crit, orc)] = (sel, int(ordenado.loc[acum <= orc, "secoes"].sum()) if orc < 10**9 else int(P["secoes"].sum()))

    res = []
    for (crit, orc), (sel, custo) in selecoes.items():
        if orc == 0 and crit != CRITERIOS[0]:
            continue
        for uf in ufs:
            sec, cands = dados[uf]
            final = sec[cands].sum() / sec[cands].sum().sum()
            camp = final.idxmax()
            for p in MARCOS:
                pr = projeta(sec, cands, max(5, int(len(sec) * p / 100)), sel, curvas)
                res.append({"crit": crit if orc else "nenhuma", "orc": orc, "custo": custo,
                            "p": p, "err": 100 * abs(pr[camp] - final[camp])})
        print(f"  {crit} {orc} ok", flush=True)

    d = pd.DataFrame(res)
    print("\nERRO MEDIANO DO LIDER por criterio de mira e orcamento de secoes")
    piv = d.pivot_table(index=["crit", "orc"], columns="p", values="err", aggfunc="median").round(2)
    custo = d.groupby(["crit", "orc"])["custo"].first()
    print(piv.assign(secoes=custo).to_string())


if __name__ == "__main__":
    main()
