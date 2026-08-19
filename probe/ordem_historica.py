"""Da para des-enviesar o parcial municipal usando a ORDEM da eleicao anterior?

O feed municipal diz quanto o municipio ja apurou, mas nao QUAIS secoes entraram -- e por
isso o modelo tem que supor que o apurado representa a cidade inteira. Quando a cidade apura
de um lado politico para o outro, essa suposicao e falsa e o parcial vem torto.

Mas a ordem se repete entre eleicoes (correlacao de +0,53 nas 200 maiores cidades). Entao da
para aprender em 2018 a "curva de chegada" de cada municipio -- qual o eixo medio das secoes
que compoem os primeiros f% a chegar -- e usar essa curva em 2022 para corrigir o parcial.

Tres cenarios comparados:
  municipio cru       -> supoe que o apurado representa a cidade (o que o feed permite hoje)
  municipio corrigido -> usa a curva de chegada de 2018 para estimar o vies do parcial
  secao               -> ve exatamente quais secoes entraram (o crawl caro)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.modelo_estadual import BASE, CHAVE, K_B, K_MUN, monta

GRADE = np.linspace(0.05, 1.0, 20)
MARCOS = [1, 2, 3, 5, 10, 20, 50]


def curvas_2018() -> dict:
    """Por municipio: eixo medio acumulado das secoes conforme elas chegaram em 2018."""
    car = pd.read_parquet(BASE / "carimbos_presidente_2018_t1.parquet")
    a = pd.read_parquet(BASE / "presidente_secao_2018.parquet")
    dois = a["t2_esq"] + a["t2_dir"]
    a = a.assign(z=(a["t2_esq"] - a["t2_dir"]) / dois.where(dois > 0))[CHAVE + ["z"]]
    d = car.merge(a, on=CHAVE).dropna(subset=["z", "prim_tot"])
    out = {}
    for cd, g in d.groupby("cd_municipio", sort=False):
        g = g.sort_values("prim_tot")
        w = g["aptos"].to_numpy(float)
        z = g["z"].to_numpy()
        cw, cz = np.cumsum(w), np.cumsum(w * z)
        frac = cw / cw[-1]
        out[cd] = np.interp(GRADE, frac, cz / np.maximum(cw, 1e-9))
    return out


def projeta(sec, cands, n, modo, curvas):
    w = sec["validos"].to_numpy(float)[:n]
    if w.sum() <= 0:
        return pd.Series(dtype=float)
    z_todos = sec["z"].to_numpy(); aptos = sec["aptos"].to_numpy(float)
    cod, uniq = pd.factorize(sec["cd_municipio"])
    nmun = len(uniq); m_ap, m_f = cod[:n], cod[n:]
    z_mun = (np.bincount(cod, weights=aptos * z_todos, minlength=nmun)
             / np.bincount(cod, weights=aptos, minlength=nmun))

    if modo == "secao":
        z_obs = z_todos[:n]
    else:
        # fracao ja apurada de cada municipio -- isso o feed municipal informa
        ap_m = np.bincount(m_ap, weights=aptos[:n], minlength=nmun)
        tot_m = np.bincount(cod, weights=aptos, minlength=nmun)
        frac = np.clip(ap_m / np.maximum(tot_m, 1e-9), 0.01, 1.0)
        if modo == "municipio_cru":
            z_est = z_mun
        else:                                   # corrigido pela curva de 2018
            z_est = z_mun.copy()
            for i, cd in enumerate(uniq):
                c = curvas.get(cd)
                if c is None:
                    continue
                # desvio previsto do parcial em relacao a media da cidade, na fracao atual
                z_est[i] = z_mun[i] + (np.interp(frac[i], GRADE, c) - c[-1])
        z_obs = z_est[m_ap]

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
    curvas = curvas_2018()
    print(f"curvas de chegada aprendidas em 2018: {len(curvas):,} municipios\n", flush=True)
    ufs = sorted(pd.read_parquet(BASE / "governador_secao_2022_t1.parquet")["uf"].unique())
    res = []
    for uf in ufs:
        sec, cands = monta(uf)
        final = sec[cands].sum() / sec[cands].sum().sum()
        o = final.sort_values(ascending=False)
        dupla, camp, margem = set(o.index[:2]), o.index[0], o.iloc[0] - o.iloc[1]
        for p in MARCOS:
            n = max(5, int(len(sec) * p / 100))
            for modo in ("municipio_cru", "municipio_corrigido", "secao"):
                pr = projeta(sec, cands, n, modo, curvas)
                po = pr.sort_values(ascending=False)
                res.append({"uf": uf, "p": p, "modo": modo,
                            "err": 100 * abs(pr[camp] - final[camp]),
                            "dupla_ok": set(po.index[:2]) == dupla,
                            "err_margem": 100 * abs((po.iloc[0] - po.iloc[1]) - margem)})
        print(f"  {uf} ok", flush=True)

    d = pd.DataFrame(res)
    col = ["municipio_cru", "municipio_corrigido", "secao"]
    for titulo, campo, agg in (("erro mediano do lider", "err", "median"),
                               ("pior erro do lider", "err", "max"),
                               ("erro mediano da margem", "err_margem", "median")):
        print(f"\n{titulo}")
        print(d.pivot_table(index="p", columns="modo", values=campo, aggfunc=agg)[col].round(2).to_string())


if __name__ == "__main__":
    main()
