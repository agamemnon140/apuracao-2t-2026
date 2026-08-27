"""Centroides dos setores censitarios da malha 2010 (shp por UF, CD_GEOCODI).

Saida: sintetico/setor_centroides_2010.parquet (cd_setor, lon, lat).

Uso:  .venv/Scripts/python -m sintetico.centroides2010
"""
from __future__ import annotations

import sys
import time
import zipfile

import pandas as pd
import pyogrio

from .caminhos import BRUTO_IBGE, SAIDA, UFS


def main() -> int:
    partes = []
    for uf in UFS:
        caminho = BRUTO_IBGE / "censo2010" / f"malha_{uf}.zip"
        shp = [n for n in zipfile.ZipFile(caminho).namelist() if n.lower().endswith(".shp")][0]
        t0 = time.time()
        gdf = pyogrio.read_dataframe(f"/vsizip/{caminho.as_posix()}/{shp}")
        col = "CD_GEOCODI" if "CD_GEOCODI" in gdf.columns else \
            [c for c in gdf.columns if "GEOCOD" in c.upper()][0]
        pontos = gdf.geometry.representative_point()
        partes.append(pd.DataFrame({"cd_setor": gdf[col].astype(str),
                                    "lon": pontos.x, "lat": pontos.y}))
        print(f"{uf}: {len(gdf)} setores [{time.time() - t0:.0f}s]", flush=True)
    df = pd.concat(partes, ignore_index=True)
    df.to_parquet(SAIDA / "setor_centroides_2010.parquet", index=False)
    print(f"{len(df)} centroides, gravado {SAIDA / 'setor_centroides_2010.parquet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
