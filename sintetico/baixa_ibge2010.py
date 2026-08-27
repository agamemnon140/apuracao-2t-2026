"""Baixa o lado IBGE do Censo 2010: agregados por setores (universo) e malha de setores.

Uso:  .venv/Scripts/python -m sintetico.baixa_ibge2010
"""
from __future__ import annotations

import sys
import time

from .baixa import baixa
from .caminhos import BRUTO_IBGE, UFS

AGREG = ("https://ftp.ibge.gov.br/Censos/Censo_Demografico_2010/Resultados_do_Universo/"
         "Agregados_por_Setores_Censitarios")
MALHA = ("https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/"
         "malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2010/"
         "setores_censitarios_shp")

PARTES_AGREG = [uf for uf in UFS if uf != "SP"] + ["SP_Capital", "SP_Exceto_Capital"]

ALVOS = [(f"{AGREG}/{p}_20260615.zip", BRUTO_IBGE / "censo2010" / f"agregados_{p}.zip")
         for p in PARTES_AGREG]
ALVOS += [(f"{MALHA}/{uf.lower()}/{uf.lower()}_setores_censitarios.zip",
           BRUTO_IBGE / "censo2010" / f"malha_{uf}.zip") for uf in UFS]


def main() -> int:
    falhas = 0
    for url, destino in ALVOS:
        t0 = time.time()
        r = baixa(url, destino)
        print(f"{destino.name:40s} {r}  [{time.time() - t0:.0f}s]", flush=True)
        if r.startswith(("HTTP", "erro")):
            falhas += 1
    print(f"concluido, {falhas} falha(s)", flush=True)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
