"""Calibra a forca do efeito de municipio (k_mun) nas 27 corridas de governador de 2022.

`k_mun` e o encolhimento: o desvio de um municipio so conta na proporcao
`votos_apurados_no_municipio / (votos_apurados + k_mun)`. k pequeno confia rapido demais
num municipio com duas secoes; k grande joga fora a informacao local.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.modelo_estadual import BASE, monta

K_B = 0.05
KS = [None, 300.0, 1000.0, 3000.0]
MARCOS = [0.5, 1, 2, 3, 5, 10, 20, 50]


def projeta(sec, cands, n, k_mun, cod_mun, nmun):
    ap_w = sec["validos"].to_numpy(float)[:n]
    if ap_w.sum() <= 0:
        return pd.Series(dtype=float)
    z_ap, z_f = sec["z"].to_numpy()[:n], sec["z"].to_numpy()[n:]
    zb = float(np.average(z_ap, weights=ap_w))
    szz = float((ap_w * (z_ap - zb) ** 2).sum())
    k = K_B * float(sec["validos"].sum() * sec["z"].var())
    taxa = ap_w.sum() / sec["aptos"].to_numpy()[:n].sum()
    v_f = sec["aptos"].to_numpy(float)[n:] * taxa
    m_ap, m_f = cod_mun[:n], cod_mun[n:]

    out = {}
    for c in cands:
        y = sec[c].to_numpy(float)[:n] / ap_w
        yb = float(np.average(y, weights=ap_w))
        b = float((ap_w * (z_ap - zb) * (y - yb)).sum()) / (szz + k) if (szz + k) > 0 else 0.0
        a = yb - b * zb
        y_f = a + b * z_f
        if k_mun is not None:
            r = y - (a + b * z_ap)
            num = np.bincount(m_ap, weights=ap_w * r, minlength=nmun)
            den = np.bincount(m_ap, weights=ap_w, minlength=nmun) + k_mun
            y_f = y_f + (num / den)[m_f]
        out[c] = float((ap_w * y).sum() + (v_f * np.clip(y_f, 0, 1)).sum())
    s = pd.Series(out)
    return s / s.sum()


def main() -> None:
    ufs = sorted(pd.read_parquet(BASE / "governador_secao_2022_t1.parquet")["uf"].unique())
    res = []
    for uf in ufs:
        sec, cands = monta(uf)
        cod, uniq = pd.factorize(sec["cd_municipio"])
        final = sec[cands].sum() / sec[cands].sum().sum()
        o = final.sort_values(ascending=False)
        dupla, camp = set(o.index[:2]), o.index[0]
        for p in MARCOS:
            n = max(5, int(len(sec) * p / 100))
            for km in KS:
                pr = projeta(sec, cands, n, km, cod, len(uniq))
                po = pr.sort_values(ascending=False)
                res.append({"uf": uf, "p": p, "k": "so eixo" if km is None else f"k={int(km)}",
                            "dupla": set(po.index[:2]) == dupla,
                            "err": 100 * abs(pr[camp] - final[camp])})
        print(f"  {uf} ok", flush=True)

    d = pd.DataFrame(res)
    ordem = ["so eixo"] + [f"k={int(x)}" for x in KS[1:]]
    for titulo, agg in (("ERRO MEDIANO do lider", "median"), ("PIOR ERRO", "max")):
        print(f"\n{titulo}")
        print(d.pivot_table(index="p", columns="k", values="err", aggfunc=agg).round(2)[ordem].to_string())
    print("\nDUPLA CERTA (%)")
    print(d.pivot_table(index="p", columns="k", values="dupla", aggfunc="mean").mul(100).round(0)[ordem].to_string())


if __name__ == "__main__":
    main()
