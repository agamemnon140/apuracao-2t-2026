"""Monta o JSON do front Regua do Quociente: quociente, needle, target, ritmo e regioes.

Por agremiacao: votos projetados, quocientes, cadeiras por QP, cadeiras esperadas com IC
(p10/mediana/p90 dos sorteios), e os MINIMOS para eleger — o QE (1 cadeira por quociente),
o piso individual de vaga de quociente (10% do QE), o piso de sobra (20% do QE) e o corte
PRATICO (votos do ultimo eleito projetado da agremiacao).

Por candidato: P(eleito), votos ja contabilizados, votos projetados, target ate o corte,
ritmo (fracao apurada do candidato / fracao apurada do estado; 100 = sem vento) e as 3
cidades que mais concentram o voto dele no apurado.

Uso:  .venv/Scripts/python -m probe.monta_demo [federal|estadual] [pct]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.needle_dep import carrega, estado, vento_uf

CARGO = sys.argv[1] if len(sys.argv) > 1 else "federal"
P = float(sys.argv[2]) if len(sys.argv) > 2 else 10
BASE = Path("D:/Claude/eleicoes-dados/baseline")


def main() -> None:
    nd = pd.read_parquet(BASE / f"needle_{CARGO}_p{P:g}.parquet")
    seats = pd.read_parquet(BASE / f"seats_{CARGO}_p{P:g}.parquet")
    nomes_mun = json.loads((BASE / "mun_nomes.json").read_text("utf-8"))
    dados = carrega(CARGO)
    votos_l, cand, _of, car, cadeiras_uf = dados

    saida = {}
    for uf in sorted(nd["uf"].unique()):
        d = nd[nd["uf"] == uf].copy()
        v = vento_uf(CARGO, uf, P, dados=dados)
        d = d.merge(v, on="nr", how="left")

        sec, comp, n, pr, validos, _na, _va, _f = estado(votos_l, cand, car, uf, P)
        qe = validos / cadeiras_uf[uf]

        su = seats[seats["uf"] == uf]
        ndraws = int(seats["draw"].max()) + 1
        piv = (su.pivot_table(index="draw", columns="agr", values="seats", aggfunc="sum")
               .reindex(range(ndraws)).fillna(0))

        agrs = []
        for a, g in d.groupby("agr"):
            votos_a = float(pr.get(a, 0) * validos)
            g = g.sort_values("votos_proj", ascending=False)
            corte = g["corte_agr"].dropna()
            corte = float(corte.iloc[0]) if len(corte) else None
            ic = ([int(np.percentile(piv[a], 10)), int(piv[a].median()),
                   int(np.percentile(piv[a], 90))] if a in piv.columns else [0, 0, 0])
            mostra = g[g["p_eleito"] >= 0.01]
            extra = g[~g.index.isin(mostra.index)].head(2)
            gg = pd.concat([mostra, extra]).sort_values("votos_proj", ascending=False)
            agrs.append({
                "agr": a, "votos": round(votos_a), "quocientes": round(votos_a / qe, 2),
                "qp": int(votos_a // qe), "ic": ic,
                "corte": (round(corte) if corte else None),
                "cands": [{
                    "nome": str(r["nome"])[:26], "pt": str(r["partido"]),
                    "p": round(float(r["p_eleito"]), 3),
                    "v": round(float(r["votos_proj"])),
                    "vap": round(float(r["votos_apurados"])),
                    "ritmo": (float(r["ritmo"]) if pd.notna(r["ritmo"]) else None),
                    "tgt": (round(float(r["target"])) if pd.notna(r["target"]) else None),
                    "in": bool(r["eleito_agora"]),
                    "reg": [[nomes_mun.get(str(m).lstrip("0"), str(m)), int(vv)]
                            for m, vv in (r["top3"] if isinstance(r["top3"], (list, np.ndarray))
                                          else [])][:3],
                    "fim": bool(r["eleito_final"]),
                } for _, r in gg.iterrows()],
            })
        agrs.sort(key=lambda x: -x["votos"])
        saida[uf] = {"qe": round(qe), "cadeiras": cadeiras_uf[uf],
                     "pct_secoes": round(100 * n / len(sec), 1), "agrs": agrs}
        print(f"  {uf} ok", flush=True)

    destino = BASE / f"demo_{CARGO}_p{P:g}.json"
    destino.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), "utf-8")
    ncand = sum(len(a["cands"]) for u in saida.values() for a in u["agrs"])
    print(f"\n{destino}  ({destino.stat().st_size/1e3:.0f} KB, {ncand:,} candidatos)")


if __name__ == "__main__":
    main()
