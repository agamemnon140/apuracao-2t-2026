"""Sondagem 1: quais caminhos do ciclo ele2022 ainda respondem, e com que cargos.

Nao adivinha padrao de URL: cruza os tipos de arquivo declarados em ele-c.json
(a, cm, e, cs, ab, u) com o padrao -r.json de dados-simplificados, e reporta
a matriz de status. O que responder 200 vira o contrato do coletor.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import fetch  # noqa: E402

BASE = "https://resultados.tse.jus.br/oficial"
CICLO = "ele2022"
CARGOS = {"0001": "Presidente", "0003": "Governador", "0005": "Senador",
          "0006": "Dep. Federal", "0007": "Dep. Estadual"}
ELEICOES = ["544", "545"]          # 1o e 2o turno de 2022 (a confirmar)
MUN_SP = "71072"                   # Sao Paulo capital


def linhas(ele: str):
    e = f"e000{ele}"
    for cargo in CARGOS:
        yield f"simplificado br  c{cargo}", f"{BASE}/{CICLO}/{ele}/dados-simplificados/br/br-c{cargo}-{e}-r.json"
        yield f"simplificado sp  c{cargo}", f"{BASE}/{CICLO}/{ele}/dados-simplificados/sp/sp-c{cargo}-{e}-r.json"
        yield f"dados        br  c{cargo}", f"{BASE}/{CICLO}/{ele}/dados/br/br-c{cargo}-{e}-v.json"
        yield f"dados        sp  c{cargo}", f"{BASE}/{CICLO}/{ele}/dados/sp/sp-c{cargo}-{e}-v.json"
        yield f"mun sp{MUN_SP}  c{cargo}", f"{BASE}/{CICLO}/{ele}/dados/sp/sp{MUN_SP}-c{cargo}-{e}-u.json"
    yield "config municipios ", f"{BASE}/{CICLO}/{ele}/config/mun-{e}-cm.json"
    yield "config abrang. br ", f"{BASE}/{CICLO}/{ele}/config/br/br-{e}-a.json"
    yield "config abrang. sp ", f"{BASE}/{CICLO}/{ele}/config/sp/sp-{e}-a.json"


def main() -> None:
    for ele in ELEICOES:
        print(f"\n=== eleicao {ele} ===")
        for rotulo, url in linhas(ele):
            st, body = fetch.get(url)
            marca = "OK " if st == 200 else "   "
            tam = f"{len(body):>9,}" if st == 200 else ""
            print(f"{marca}{st:>4}  {rotulo}  {tam}  {url.split('/oficial/')[1]}")


if __name__ == "__main__":
    main()
