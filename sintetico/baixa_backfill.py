"""Baixa os brutos do TSE para o backfill 2010/2014/2018.

Uso:  .venv/Scripts/python -m sintetico.baixa_backfill
"""
from __future__ import annotations

import sys
import time

from .baixa import baixa
from .caminhos import BRUTO_TSE, UFS

CDN = "https://cdn.tse.jus.br/estatistica/sead/odsele"
ANOS = [2010, 2014, 2018]

ALVOS = []
for ano in ANOS:
    ALVOS += [
        (f"{CDN}/votacao_secao/votacao_secao_{ano}_BR.zip",
         BRUTO_TSE / str(ano) / f"votacao_secao_{ano}_BR.zip"),
        (f"{CDN}/detalhe_votacao_secao/detalhe_votacao_secao_{ano}.zip",
         BRUTO_TSE / str(ano) / f"detalhe_votacao_secao_{ano}.zip"),
        (f"{CDN}/eleitorado_locais_votacao/eleitorado_local_votacao_{ano}.zip",
         BRUTO_TSE / str(ano) / f"eleitorado_local_votacao_{ano}.zip"),
    ]
    ALVOS += [(f"{CDN}/perfil_eleitor_secao/perfil_eleitor_secao_{ano}_{uf}.zip",
               BRUTO_TSE / str(ano) / "perfil_secao" / f"perfil_eleitor_secao_{ano}_{uf}.zip")
              for uf in UFS]


def main() -> int:
    falhas = 0
    for url, destino in ALVOS:
        t0 = time.time()
        r = baixa(url, destino)
        print(f"{destino.name:48s} {r}  [{time.time() - t0:.0f}s]", flush=True)
        if r.startswith(("HTTP", "erro")):
            falhas += 1
    print(f"concluido, {falhas} falha(s)", flush=True)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
