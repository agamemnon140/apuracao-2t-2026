"""Quanto vale saber a SECAO, e nao so o municipio ou o estado?

A ancora do modelo e `z_i`: como aquela secao votou no 2o turno presidencial anterior. Este
teste degrada a ancora de proposito e mede o estrago:

  secao     -> z proprio da secao            (o que o modelo usa hoje)
  municipio -> z medio do municipio dela     (perde a variacao dentro da cidade)
  uf        -> z medio do estado             (so o eixo estadual sobra)

Cruzado com ligar/desligar o efeito de municipio aprendido AO VIVO, para separar duas coisas
que se confundem: informacao historica fina x aprendizado local durante a apuracao.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.modelo_estadual import BASE, K_MUN, monta, projeta

MARCOS = [1, 2, 3, 5, 10, 20, 50]


def degrada(sec: pd.DataFrame, nivel: str) -> pd.DataFrame:
    """Substitui z pela media do nivel pedido, ponderada pelo eleitorado."""
    if nivel == "secao":
        return sec
    s = sec.copy()
    if nivel == "municipio":
        med = s.groupby("cd_municipio").apply(
            lambda g: np.average(g["z"], weights=g["aptos"]), include_groups=False)
        s["z"] = s["cd_municipio"].map(med)
    else:
        s["z"] = float(np.average(s["z"], weights=s["aptos"]))
    return s


def main() -> None:
    ufs = sorted(pd.read_parquet(BASE / "governador_secao_2022_t1.parquet")["uf"].unique())
    res = []
    for uf in ufs:
        base, cands = monta(uf)
        final = base[cands].sum() / base[cands].sum().sum()
        o = final.sort_values(ascending=False)
        dupla, camp = set(o.index[:2]), o.index[0]
        margem_real = o.iloc[0] - o.iloc[1]
        for nivel in ("secao", "municipio", "uf"):
            sec = degrada(base, nivel)
            for k_mun, rot in ((K_MUN, "com efeito local"), (None, "sem efeito local")):
                for p in MARCOS:
                    pr = projeta(sec, cands, max(5, int(len(sec) * p / 100)), k_mun=k_mun)
                    if pr.empty:
                        continue
                    po = pr.sort_values(ascending=False)
                    res.append({"uf": uf, "nivel": nivel, "efeito": rot, "p": p,
                                "lider_ok": po.index[0] == camp,
                                "dupla_ok": set(po.index[:2]) == dupla,
                                "err": 100 * abs(pr[camp] - final[camp]),
                                "err_margem": 100 * abs((po.iloc[0] - po.iloc[1]) - margem_real)})
        print(f"  {uf} ok", flush=True)

    d = pd.DataFrame(res)
    for efeito in ("sem efeito local", "com efeito local"):
        g = d[d["efeito"] == efeito]
        print(f"\n===== {efeito.upper()} =====")
        for titulo, campo, agg in (("erro mediano do lider", "err", "median"),
                                   ("pior erro do lider", "err", "max"),
                                   ("dupla certa (%)", "dupla_ok", "mean")):
            piv = g.pivot_table(index="p", columns="nivel", values=campo, aggfunc=agg)
            if campo == "dupla_ok":
                piv = piv.mul(100)
            print(f"\n{titulo}")
            print(piv[["secao", "municipio", "uf"]].round(2).to_string())


if __name__ == "__main__":
    main()
