"""Vale coletar SECAO ao vivo, ou o parcial por MUNICIPIO basta?

Esta e a decisao cara do plano: a camada de secao custa centenas de milhares de requisicoes;
a municipal custa dezenas. As duas veem a mesma eleicao, mas nao a mesma coisa.

  feed de secao     -> sabemos exatamente QUAIS secoes entraram, e a ancora historica de cada uma
  feed de municipio -> sabemos o total parcial do municipio e quantas secoes entraram,
                       mas NAO quais. O melhor palpite para a ancora do que entrou e a
                       media do municipio.

A diferenca so aparece em municipio PARCIALMENTE apurado -- que e a situacao das capitais no
comeco da noite, exatamente quando o modelo mais importa.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.modelo_estadual import BASE, K_B, K_MUN, monta

MARCOS = [1, 2, 3, 5, 10, 20, 50]


def projeta(sec, cands, n, feed: str) -> pd.Series:
    """feed='secao' ve cada secao apurada; feed='municipio' ve so o total parcial do municipio."""
    w = sec["validos"].to_numpy(float)[:n]
    if w.sum() <= 0:
        return pd.Series(dtype=float)
    z_todos = sec["z"].to_numpy()
    z_ap, z_f = z_todos[:n], z_todos[n:]
    cod, uniq = pd.factorize(sec["cd_municipio"])
    m_ap, m_f, nmun = cod[:n], cod[n:], len(uniq)
    aptos = sec["aptos"].to_numpy(float)

    # ancora media do municipio (conhecida de antemao, do historico)
    z_mun = (np.bincount(cod, weights=aptos * z_todos, minlength=nmun)
             / np.bincount(cod, weights=aptos, minlength=nmun))
    # o que o observador enxerga como ancora do que ja apurou
    z_obs = z_ap if feed == "secao" else z_mun[m_ap]

    zb = float(np.average(z_obs, weights=w))
    szz = float((w * (z_obs - zb) ** 2).sum())
    k = K_B * float(sec["validos"].sum() * sec["z"].var())
    taxa = w.sum() / aptos[:n].sum()
    v_f = aptos[n:] * taxa

    out = {}
    for c in cands:
        y = sec[c].to_numpy(float)[:n] / w
        yb = float(np.average(y, weights=w))
        b = float((w * (z_obs - zb) * (y - yb)).sum()) / (szz + k) if (szz + k) > 0 else 0.0
        a = yb - b * zb
        r = y - (a + b * z_obs)
        num = np.bincount(m_ap, weights=w * r, minlength=nmun)
        den = np.bincount(m_ap, weights=w, minlength=nmun) + K_MUN
        y_f = a + b * z_f + (num / den)[m_f]
        out[c] = float((w * y).sum() + (v_f * np.clip(y_f, 0, 1)).sum())
    s = pd.Series(out)
    return s / s.sum()


def main() -> None:
    ufs = sorted(pd.read_parquet(BASE / "governador_secao_2022_t1.parquet")["uf"].unique())
    res = []
    for uf in ufs:
        sec, cands = monta(uf)
        final = sec[cands].sum() / sec[cands].sum().sum()
        o = final.sort_values(ascending=False)
        dupla, camp, margem = set(o.index[:2]), o.index[0], o.iloc[0] - o.iloc[1]
        for p in MARCOS:
            n = max(5, int(len(sec) * p / 100))
            # quanto do que ja apurou esta em municipio pela metade
            cod, _ = pd.factorize(sec["cd_municipio"])
            parciais = pd.Series(cod[:n]).nunique(), pd.Series(cod).nunique()
            for feed in ("secao", "municipio"):
                pr = projeta(sec, cands, n, feed)
                po = pr.sort_values(ascending=False)
                res.append({"uf": uf, "p": p, "feed": feed,
                            "lider_ok": po.index[0] == camp,
                            "dupla_ok": set(po.index[:2]) == dupla,
                            "err": 100 * abs(pr[camp] - final[camp]),
                            "err_margem": 100 * abs((po.iloc[0] - po.iloc[1]) - margem),
                            "mun_tocados": parciais[0]})
        print(f"  {uf} ok", flush=True)

    d = pd.DataFrame(res)
    print("\n===== feed de SECAO x feed de MUNICIPIO =====")
    for titulo, campo, agg in (("erro mediano do lider", "err", "median"),
                               ("pior erro do lider", "err", "max"),
                               ("erro mediano da margem 1o-2o", "err_margem", "median"),
                               ("dupla certa (%)", "dupla_ok", "mean")):
        piv = d.pivot_table(index="p", columns="feed", values=campo, aggfunc=agg)
        if campo == "dupla_ok":
            piv = piv.mul(100)
        piv["ganho da secao"] = piv["municipio"] - piv["secao"]
        print(f"\n{titulo}")
        print(piv.round(2).to_string())


if __name__ == "__main__":
    main()
