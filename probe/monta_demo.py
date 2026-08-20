"""Monta o JSON do front de demonstracao: quociente + needle + target + vento por UF.

Le o parquet do needle (gerado por calibra_needle_dep), calcula o vento por UF e emite um
JSON compacto por cargo, pronto para embutir na pagina.

Uso:  .venv/Scripts/python -m probe.monta_demo [federal|estadual] [pct]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from pipeline.needle_dep import CADEIRAS_EST, carrega, estado, vento_uf
from pipeline.quociente import CADEIRAS

CARGO = sys.argv[1] if len(sys.argv) > 1 else "federal"
P = float(sys.argv[2]) if len(sys.argv) > 2 else 10
BASE = Path("D:/Claude/eleicoes-dados/baseline")


def main() -> None:
    nd = pd.read_parquet(BASE / f"needle_{CARGO}_p{P:g}.parquet")
    dados = carrega(CARGO)
    votos_l, cand, _of, car, cadeiras_uf = dados
    saida = {}
    for uf in sorted(nd["uf"].unique()):
        d = nd[nd["uf"] == uf].copy()
        v = vento_uf(CARGO, uf, P, dados=dados)
        d = d.merge(v, on="nr", how="left")

        sec, comp, n, pr, validos, _na, _va, _f = estado(votos_l, cand, car, uf, P)
        qe = validos / cadeiras_uf[uf]

        agrs = []
        for a, g in d.groupby("agr"):
            votos_a = float(pr.get(a, 0) * validos)
            exp = float(g["p_eleito"].sum())
            g = g.sort_values("votos_proj", ascending=False)
            corte_ok = g[g["eleito_agora"]]
            # candidatos exibidos: quem tem chance real ou esta perto do corte
            mostra = g[(g["p_eleito"] >= 0.01)]
            extra = g[~g.index.isin(mostra.index)].head(2)      # 2 primeiros de fora
            gg = pd.concat([mostra, extra]).sort_values("votos_proj", ascending=False)
            agrs.append({
                "agr": a, "votos": round(votos_a), "quocientes": round(votos_a / qe, 2),
                "qp": int(votos_a // qe), "exp": round(exp, 1),
                "cands": [{
                    "nome": str(r["nome"])[:26], "pt": str(r["partido"]),
                    "p": round(float(r["p_eleito"]), 3),
                    "v": round(float(r["votos_proj"])),
                    "tgt": (round(float(r["target"])) if pd.notna(r["target"]) else None),
                    "in": bool(r["eleito_agora"]),
                    "vento": (round(float(r["vento"]), 2) if pd.notna(r["vento"]) else 0.0),
                    "pap": (round(float(r["pct_apurado"]), 1)
                            if pd.notna(r["pct_apurado"]) else None),
                    "fim": bool(r["eleito_final"]),
                } for _, r in gg.iterrows()],
            })
        agrs.sort(key=lambda x: -x["votos"])
        saida[uf] = {"qe": round(qe), "cadeiras": cadeiras_uf[uf],
                     "pct_secoes": round(100 * n / len(sec), 1), "agrs": agrs}
        print(f"  {uf} ok", flush=True)

    destino = BASE / f"demo_{CARGO}_p{P:g}.json"
    destino.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    ncand = sum(len(a["cands"]) for u in saida.values() for a in u["agrs"])
    print(f"\n{destino}  ({destino.stat().st_size/1e3:.0f} KB, {ncand:,} candidatos exibidos)")


if __name__ == "__main__":
    main()
