"""Exporta os boletins raspados (live/bu.sqlite) para o mapa: 2026 por urna, local, zona e
municipio.

Saida: docs/dados/live/mun/{cd}.json (fora do git: servido pelo modo local/tunel)
  {"instante", "n_bu", "mun": U, "zonas": {z: U}, "locais": {"z:l": U}, "secoes": {"z:s": U}}
  U = {"pr"|"gov"|"sen"|"df"|"de": {"c": {nr: votos}, "l": {partido: legenda}, "b": brancos,
                                    "n": nulos, "a": abstencao, "apt": aptos}}

Presidente, governador e senador vao ate a urna. Deputados so ate a zona: por urna seriam
milhoes de linhas em Sao Paulo capital (agregados direto no SQLite).
So reescreve municipios que ganharam boletim; municipios grandes no maximo a cada 5 min.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter
from pathlib import Path

import pandas as pd

CARGO = {"PRESIDENTE": "pr", "GOVERNADOR": "gov", "SENADOR": "sen", "DEPUTADO FEDERAL": "df",
         "DEPUTADO ESTADUAL": "de", "DEPUTADO DISTRITAL": "de"}
MAJ = ("PRESIDENTE", "GOVERNADOR", "SENADOR")
GRANDE, INTERVALO_GRANDE = 1500, 300.0
_ultimo: dict = {}


def _novo():
    return {"c": Counter(), "l": Counter(), "b": 0, "n": 0, "a": 0, "apt": 0}


def _soma(dst: dict, src: dict) -> None:
    for k, u in src.items():
        d = dst.setdefault(k, _novo())
        d["c"].update(u["c"]); d["l"].update(u["l"])
        for x in ("b", "n", "a", "apt"):
            d[x] += u[x]


def _json(u: dict) -> dict:
    return {k: {"c": dict(v["c"]), "l": dict(v["l"]), "b": v["b"], "n": v["n"], "a": v["a"], "apt": v["apt"]}
            for k, v in u.items()}


def um_municipio(con, uf: str, mun: int, local_de: dict) -> dict:
    sec: dict = {}
    for z, s, cargo, apt, comp, br, nu in con.execute(
            "SELECT zona, secao, cargo, aptos, comparecimento, brancos, nulos FROM resumo WHERE uf=? AND mun=? "
            "AND cargo IN (?,?,?)", (uf, mun, *MAJ)):
        u = sec.setdefault((z, s), {}).setdefault(CARGO[cargo], _novo())
        u.update(b=br or 0, n=nu or 0, a=max((apt or 0) - (comp or 0), 0), apt=apt or 0)
    for z, s, cargo, nr, v in con.execute(
            "SELECT zona, secao, cargo, nr, votos FROM votos WHERE uf=? AND mun=? AND cargo IN (?,?,?)",
            (uf, mun, *MAJ)):
        u = sec.get((z, s), {}).get(CARGO[cargo])
        if u is not None and v:
            (u["l"] if nr.startswith("L") else u["c"])[nr.lstrip("L")] += v
    zonas: dict = {}
    locais: dict = {}
    total: dict = {}
    for (z, s), u in sec.items():
        _soma(zonas.setdefault(z, {}), u)
        lc = local_de.get((z, s))
        if lc is not None:
            _soma(locais.setdefault(f"{z}:{lc}", {}), u)
        _soma(total, u)
    # deputados: agregados por zona no proprio SQLite
    dep_z: dict = {}
    for z, cargo, apt, comp, br, nu in con.execute(
            "SELECT zona, cargo, SUM(aptos), SUM(comparecimento), SUM(brancos), SUM(nulos) FROM resumo "
            "WHERE uf=? AND mun=? AND cargo LIKE 'DEPUTADO%' GROUP BY zona, cargo", (uf, mun)):
        u = dep_z.setdefault(z, {}).setdefault(CARGO[cargo], _novo())
        u.update(b=br or 0, n=nu or 0, a=max((apt or 0) - (comp or 0), 0), apt=apt or 0)
    for z, cargo, nr, v in con.execute(
            "SELECT zona, cargo, nr, SUM(votos) FROM votos WHERE uf=? AND mun=? AND cargo LIKE 'DEPUTADO%' "
            "GROUP BY zona, cargo, nr", (uf, mun)):
        u = dep_z.get(z, {}).get(CARGO[cargo])
        if u is not None and v:
            (u["l"] if nr.startswith("L") else u["c"])[nr.lstrip("L")] += v
    for z, u in dep_z.items():
        _soma(zonas.setdefault(z, {}), u)
        _soma(total, u)
    return {"instante": time.strftime("%H:%M:%S"), "n_bu": len(sec), "mun": _json(total),
            "zonas": {str(z): _json(u) for z, u in zonas.items()},
            "locais": {k: _json(u) for k, u in locais.items()},
            "secoes": {f"{z}:{s}": _json(u) for (z, s), u in sec.items()}}


def exporta(anc: pd.DataFrame, db: Path, destino: Path, desde: float = 0.0) -> tuple[int, float]:
    """anc: urnas 2026 (uf, cd_mun, zona, secao, nr_local). Devolve (municipios escritos, novo 'desde')."""
    if not db.exists():
        return 0, desde
    con = sqlite3.connect(db, timeout=30)
    novos = con.execute("SELECT uf, mun, COUNT(DISTINCT zona || ':' || secao) FROM resumo WHERE coletado > ? "
                        "GROUP BY uf, mun", (desde,)).fetchall()
    agora = time.time()
    n, adiados = 0, False
    for uf, mun, _ in novos:
        tam = con.execute("SELECT COUNT(*) FROM secoes WHERE uf=? AND mun=?", (uf, mun)).fetchone()[0]
        if tam > GRANDE and agora - _ultimo.get((uf, mun), 0) < INTERVALO_GRANDE:
            adiados = True
            continue
        a = anc[(anc["uf"].str.lower() == uf) & (anc["cd_mun"] == int(mun))]
        local_de = dict(zip(zip(a["zona"], a["secao"]), a["nr_local"]))
        doc = um_municipio(con, uf, int(mun), local_de)
        destino.mkdir(parents=True, exist_ok=True)
        tmp = destino / f"{int(mun)}.json.tmp"
        tmp.write_text(json.dumps(doc, separators=(",", ":")), "utf-8")
        tmp.replace(destino / f"{int(mun)}.json")
        _ultimo[(uf, mun)] = agora
        n += 1
    con.close()
    # municipio grande adiado continua pendente: nao avanca o marcador alem dele
    return n, (desde if adiados else agora)
