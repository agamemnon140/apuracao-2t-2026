"""Vigia o indice de pleitos do TSE e avisa quando algo novo aparece.

Duas coisas que precisamos pegar assim que forem publicadas:

1. **A eleicao geral de 2026** -- o codigo (pleito e eleicao) nao existe ainda. Sem ele,
   nenhum caminho de resultado pode ser montado. Cravar numero no codigo e o erro classico.
2. **Eleicoes suplementares** -- cada uma e uma noite de apuracao real, com a mesma
   infraestrutura, para ensaiar o coletor antes de outubro. Elas so entram no indice
   perto da data.

Guarda um retrato em disco e reporta a diferenca. Feito para rodar no cron diario.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdn  # noqa: E402

URL = "https://resultados.tse.jus.br/oficial/comum/config/ele-c.json"
RETRATO = Path(r"D:\Claude\eleicoes-dados\ele-c.retrato.json")


def pleitos() -> dict:
    j = json.loads(urllib.request.urlopen(urllib.request.Request(URL, headers=cdn.H), timeout=60).read())
    out = {}
    for p in j.get("pl", []):
        for e in p.get("e", []):
            out[f"{p['cd']}/{e['cd']}"] = {
                "pleito": p["cd"], "eleicao": e["cd"], "data": p.get("dt", ""),
                "nome": e.get("nm", ""), "turno": e.get("t", ""),
                "cargos": sorted({c["ds"] for a in e.get("abr", []) for c in a.get("cp", [])}),
            }
    return out


def data_br(s: str) -> dt.date | None:
    try:
        d, m, a = s.split("/")
        return dt.date(int(a), int(m), int(d))
    except Exception:
        return None


def main() -> None:
    atual = pleitos()
    antes = json.loads(RETRATO.read_text("utf-8")) if RETRATO.exists() else {}
    novos = {k: v for k, v in atual.items() if k not in antes}

    hoje = dt.date.today()
    futuros = sorted((v for v in atual.values() if (d := data_br(v["data"])) and d >= hoje),
                     key=lambda v: v["data"])

    print(f"pleitos no indice: {len(atual)}   novos desde o ultimo retrato: {len(novos)}")
    for v in novos.values():
        print(f"  NOVO  {v['data']}  pleito {v['pleito']} / eleicao {v['eleicao']}  {v['nome']}")
    print(f"\neleicoes com data futura ({hoje:%d/%m/%Y} em diante): {len(futuros)}")
    for v in futuros:
        print(f"  {v['data']}  pleito {v['pleito']} / eleicao {v['eleicao']}  {v['nome'][:60]}  {v['cargos']}")
    if not futuros:
        print("  nenhuma -- suplementares e a geral de 2026 ainda nao foram configuradas")

    RETRATO.parent.mkdir(parents=True, exist_ok=True)
    RETRATO.write_text(json.dumps(atual, ensure_ascii=False, indent=1), "utf-8")


if __name__ == "__main__":
    main()
