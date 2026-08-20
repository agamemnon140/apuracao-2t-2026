"""P(eleito) por deputado: quando o needle diz X%, o candidato entra X% das vezes?

Referencia: o alocador aplicado aos totais finais (a 'verdade da urna').

Uso:  .venv/Scripts/python -m probe.calibra_needle_dep [federal|estadual] [pct]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from pipeline.needle_dep import carrega, needle_uf

CARGO = sys.argv[1] if len(sys.argv) > 1 else "federal"
P = float(sys.argv[2]) if len(sys.argv) > 2 else 10
BASE = Path("D:/Claude/eleicoes-dados/baseline")


def main() -> None:
    bruto = json.loads((BASE / f"calib_{CARGO}.json").read_text())
    calib = {(int(float(k)) if float(k) == int(float(k)) else float(k)): v
             for k, v in bruto.items()}
    dados = carrega(CARGO)
    todos, seats = [], []
    for uf in sorted(dados[0]["uf"].unique()):
        df, meta = needle_uf(CARGO, uf, P, calib, ndraws=250, dados=dados)
        todos.append(df)
        seats.append(meta["seats_draws"].assign(uf=uf))
        print(f"  {uf} ok ({meta['pct_secoes']:.1f}% das secoes)", flush=True)
    d = pd.concat(todos)
    d.to_parquet(BASE / f"needle_{CARGO}_p{P:g}.parquet", index=False)
    pd.concat(seats).to_parquet(BASE / f"seats_{CARGO}_p{P:g}.parquet", index=False)

    print(f"\n{CARGO.upper()} com {P:g}% apurado — {len(d):,} candidatos")
    d["faixa"] = pd.cut(d["p_eleito"], [-.001, .02, .1, .3, .5, .7, .9, .98, 1.001],
                        labels=["0-2", "2-10", "10-30", "30-50", "50-70", "70-90",
                                "90-98", "98-100"])
    tab = d.groupby("faixa", observed=True).agg(previsto=("p_eleito", "mean"),
                                                observado=("eleito_final", "mean"),
                                                n=("nr", "size"))
    tab[["previsto", "observado"]] = (100 * tab[["previsto", "observado"]]).round(1)
    print(tab.to_string())
    print(f"\nBrier: {((d['p_eleito'] - d['eleito_final']) ** 2).mean():.4f}")
    print(f"corte em 50%: {((d['p_eleito'] > .5) == d['eleito_final']).sum()}/{len(d)} certos; "
          f"eleitos reais com P>50%: "
          f"{int((d[d['eleito_final']]['p_eleito'] > .5).sum())}/{int(d['eleito_final'].sum())}")


if __name__ == "__main__":
    main()
