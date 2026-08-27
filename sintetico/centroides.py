"""Extrai o centroide de cada setor censitario da malha 2022 (gpkg de 1,5 GB).

Le por UF para nao estourar memoria; so CD_SETOR + geometria. Usa representative_point
(garantido dentro do poligono -- setores em L ou anel teriam centroide fora).

Saida: sintetico/setor_centroides_2022.parquet (cd_setor, lon, lat).

Uso:  .venv/Scripts/python -m sintetico.centroides
"""
from __future__ import annotations

import sys
import time

import pandas as pd
import pyogrio

from .caminhos import BRUTO_IBGE, SAIDA

GPKG = BRUTO_IBGE / "BR_setores_CD2022.gpkg"
UFS_COD = ["11", "12", "13", "14", "15", "16", "17", "21", "22", "23", "24", "25",
           "26", "27", "28", "29", "31", "32", "33", "35", "41", "42", "43", "50",
           "51", "52", "53"]


def main() -> int:
    partes = []
    for cod in UFS_COD:
        t0 = time.time()
        gdf = pyogrio.read_dataframe(GPKG, layer="BR_setores_CD2022",
                                     columns=["CD_SETOR"], where=f"CD_UF = '{cod}'")
        pontos = gdf.geometry.representative_point()
        partes.append(pd.DataFrame({"cd_setor": gdf["CD_SETOR"].astype(str),
                                    "lon": pontos.x, "lat": pontos.y}))
        print(f"UF {cod}: {len(gdf)} setores [{time.time() - t0:.0f}s]", flush=True)

    df = pd.concat(partes, ignore_index=True)
    destino = SAIDA / "setor_centroides_2022.parquet"
    df.to_parquet(destino, index=False)
    print(f"{len(df)} centroides, gravado {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
