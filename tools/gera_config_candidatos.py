"""Gera config/candidatos_2026.json a partir de consulta_cand_2026 (dados abertos do TSE).

Estrutura:
  {"gerado_em", "fonte", "eleicoes": {"presidente": "6257", "estaduais": "6259"},
   "presidente": {"esq": "13", "dir": "22", "cands": {nr: {nome, partido}}},
   "governador": {UF: {nr: {nome, partido}}}, "senador": {UF: {...}},
   "depfederal": {UF: {nr: {nome, partido}}}, "depestadual": {UF: {...}}}

Deputado distrital (DF) entra como depestadual. Vices e suplentes ficam de fora.
Overrides manuais: config/candidatos_2026.override.json, mesclado por cima (chave a chave).

Uso:  .venv/Scripts/python tools/gera_config_candidatos.py
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import sys
import zipfile
from pathlib import Path
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
from sintetico.caminhos import BRUTO_TSE

RAIZ = Path(__file__).resolve().parents[1]
ZIP = BRUTO_TSE / "2026" / "consulta_cand_2026.zip"
SAIDA = RAIZ / "config" / "candidatos_2026.json"
OVERRIDE = RAIZ / "config" / "candidatos_2026.override.json"

CARGOS = {"PRESIDENTE": "presidente", "GOVERNADOR": "governador", "SENADOR": "senador",
          "DEPUTADO FEDERAL": "depfederal", "DEPUTADO ESTADUAL": "depestadual",
          "DEPUTADO DISTRITAL": "depestadual"}
# campos do segundo turno presidencial que o needle acompanha
ESQ, DIR = "13", "22"


def mescla(a: dict, b: dict) -> dict:
    for k, v in b.items():
        a[k] = mescla(a.get(k, {}), v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return a


def main() -> int:
    z = zipfile.ZipFile(ZIP)
    with z.open("consulta_cand_2026_BRASIL.csv") as fh:
        rows = list(csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";"))
    out: dict = {"gerado_em": dt.datetime.now().isoformat(timespec="seconds"),
                 "fonte": f"{ZIP.name} (DT_GERACAO {rows[0]['DT_GERACAO']} {rows[0]['HH_GERACAO']})",
                 "eleicoes": {}, "presidente": {"esq": ESQ, "dir": DIR, "cands": {}}}
    for c in CARGOS.values():
        out.setdefault(c, {})
    n = 0
    for r in rows:
        cargo = CARGOS.get(r["DS_CARGO"].upper())
        if not cargo or r["NR_TURNO"] != "1":
            continue
        # candidaturas indeferidas continuam na urna ate o julgamento; ficam na lista
        info = {"nome": r["NM_URNA_CANDIDATO"].strip(), "partido": r["SG_PARTIDO"].strip(),
                "nr_partido": r["NR_PARTIDO"].strip(), "situacao": r["DS_SITUACAO_CANDIDATURA"].strip()}
        if cargo == "presidente":
            out["presidente"]["cands"][r["NR_CANDIDATO"]] = info
            out["eleicoes"]["presidente"] = r["CD_ELEICAO"]
        else:
            out[cargo].setdefault(r["SG_UF"], {})[r["NR_CANDIDATO"]] = info
            out["eleicoes"]["estaduais"] = r["CD_ELEICAO"]
        n += 1
    if OVERRIDE.exists():
        mescla(out, json.loads(OVERRIDE.read_text("utf-8")))
    SAIDA.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    p = out["presidente"]
    print(f"{n} candidaturas; presidente esq={p['esq']} {p['cands'][p['esq']]['nome']}, "
          f"dir={p['dir']} {p['cands'][p['dir']]['nome']}; {len(p['cands'])} na urna")
    for c in ["governador", "senador", "depfederal", "depestadual"]:
        print(f"  {c:12s} {sum(len(v) for v in out[c].values()):6d} em {len(out[c])} UFs")
    print(f"gravado {SAIDA} ({SAIDA.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
