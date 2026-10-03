"""Banco de boletins SINTETICO para testar a noite sem o TSE: pega o voto real de 2022 de
uma UF, por secao, e grava em live/bu_teste.sqlite no mesmo esquema do bu_crawler, com os
nomes de cargo que o boletim de 2026 usa. Os numeros de 2022 (Lula 13, Bolsonaro 22)
casam com os de 2026 (13, 22) no presidente, entao o needle ao vivo consegue le-lo.

Uso:  .venv/Scripts/python tests/bu_sintetico.py AC 0.5      (UF, fracao das secoes)
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from runner.bu_crawler import conecta
from sintetico.caminhos import BASELINE, VIVO

B = BASELINE
DB = VIVO / "bu_teste.sqlite"


def main() -> int:
    uf = sys.argv[1] if len(sys.argv) > 1 else "AC"
    frac = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
    DB.unlink(missing_ok=True)
    con = conecta(DB)
    car = pd.read_parquet(B / "carimbos_presidente_2022_t1.parquet")
    car = car[car["uf"] == uf]
    car = car.sample(frac=frac, random_state=1)
    car["mun"] = car["cd_municipio"].astype(int)
    chaves = set(zip(car["mun"], car["zona"], car["secao"]))
    agora = time.time()
    res, vot = [], []
    for cargo, arq in [("PRESIDENTE", "presidente_secao_2022_t1.parquet"), ("GOVERNADOR", "governador_secao_2022_t1.parquet"),
                       ("SENADOR", "senador_secao_2022_t1.parquet")]:
        v = pd.read_parquet(B / arq, filters=[("uf", "==", uf)])
        v["mun"] = v["cd_municipio"].astype(int)
        v = v[[k in chaves for k in zip(v["mun"], v["zona"], v["secao"])]]
        for (m, z, s), g in v.groupby(["mun", "zona", "secao"]):
            c = g[g["candidato"]]
            br = int(g.loc[g["nr_votavel"] == "95", "votos"].sum())
            nu = int(g.loc[g["nr_votavel"] == "96", "votos"].sum())
            nom = int(c["votos"].sum())
            cr = car[(car["mun"] == m) & (car["zona"] == z) & (car["secao"] == s)].iloc[0]
            res.append((uf.lower(), m, z, s, cargo, int(cr["aptos"]), int(cr["comparecimento"]), nom, 0, br, nu,
                        nom + br + nu, agora))
            vot += [(uf.lower(), m, z, s, cargo, r.nr_votavel, int(r.votos)) for r in c.itertuples()]
    for cargo, arq in [("DEPUTADO FEDERAL", "depfederal_candidato_secao_2022_t1.parquet")]:
        v = pd.read_parquet(B / arq, filters=[("uf", "==", uf)])
        v["mun"] = v["cd_municipio"].astype(int)
        v = v[[k in chaves for k in zip(v["mun"], v["zona"], v["secao"])]]
        vot += [(uf.lower(), r.mun, r.zona, r.secao, cargo, r.nr, int(r.votos)) for r in v.itertuples()]
        for (m, z, s), g in v.groupby(["mun", "zona", "secao"]):
            cr = car[(car["mun"] == m) & (car["zona"] == z) & (car["secao"] == s)].iloc[0]
            res.append((uf.lower(), m, z, s, cargo, int(cr["aptos"]), int(cr["comparecimento"]), int(g["votos"].sum()),
                        0, 0, 0, int(g["votos"].sum()), agora))
    con.executemany("INSERT OR REPLACE INTO resumo VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", res)
    con.executemany("INSERT OR REPLACE INTO votos VALUES (?,?,?,?,?,?,?)", vot)
    con.executemany("INSERT OR REPLACE INTO secoes(uf, mun, zona, secao, status) VALUES (?,?,?,?,'ok')",
                    [(uf.lower(), m, z, s) for m, z, s in chaves])
    con.commit()
    print(f"{DB}: {len(chaves)} urnas, {len(res)} resumos, {len(vot)} votos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
