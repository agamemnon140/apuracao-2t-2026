"""Mede o modelo estadual nas 27 corridas de governador do 1o turno de 2022.

Uma noite de presidente e uma amostra de tamanho 1 -- da para "melhorar" um modelo em cima
dela por acidente. As 27 corridas de governador da MESMA noite sao 27 testes independentes,
e e delas que sai material para calibrar a probabilidade do needle.

Uso:  .venv/Scripts/python -m probe.avalia_estadual
"""
from __future__ import annotations

import pandas as pd

from pipeline.modelo_estadual import BASE, MARCOS, monta, projeta


def main() -> None:
    ufs = sorted(pd.read_parquet(BASE / "governador_secao_2022_t1.parquet")["uf"].unique())
    linhas = []
    for uf in ufs:
        sec, cands = monta(uf)
        final = sec[cands].sum() / sec[cands].sum().sum()
        o = final.sort_values(ascending=False)
        campeao, dupla, houve_2t = o.index[0], set(o.index[:2]), o.iloc[0] < 0.5
        for p in MARCOS:
            pr = projeta(sec, cands, max(5, int(len(sec) * p / 100)))
            if pr.empty:
                continue
            po = pr.sort_values(ascending=False)
            linhas.append({
                "uf": uf, "p": p, "lider_ok": po.index[0] == campeao,
                "dupla_ok": set(po.index[:2]) == dupla, "houve_2t": houve_2t,
                "err_lider": 100 * abs(pr[campeao] - final[campeao]),
                "err_margem": 100 * abs((po.iloc[0] - po.iloc[1]) - (o.iloc[0] - o.iloc[1])),
            })

    d = pd.DataFrame(linhas)
    n2t = int(d.groupby("uf")["houve_2t"].first().sum())
    print(f"27 corridas de governador, 1o turno de 2022")
    print(f"  decididas no 1o turno: {27 - n2t}   |   foram a 2o turno: {n2t}")
    print()
    print("  apurado  lider  dupla |  erro do lider: mediana media  pior |  erro da margem: mediana pior")
    for p, g in d.groupby("p"):
        print(f"  {p:5.1f}%  {100*g.lider_ok.mean():4.0f}%  {100*g.dupla_ok.mean():4.0f}% |"
              f"  {g.err_lider.median():14.2f} {g.err_lider.mean():5.2f} {g.err_lider.max():5.2f} |"
              f"  {g.err_margem.median():14.2f} {g.err_margem.max():5.2f}")

    ruins = (d[d["p"] <= 5].groupby("uf")["err_lider"].max().sort_values(ascending=False).head(5))
    print("\n  piores estados ate 5% apurado (erro do lider, em pontos):")
    for uf, e in ruins.items():
        print(f"    {uf}  {e:5.2f}")


if __name__ == "__main__":
    main()
