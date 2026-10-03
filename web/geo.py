"""Malhas do mapa: Brasil por UF e cada UF por municipio, em TopoJSON leve.

Fonte: API de malhas do IBGE (qualidade minima, ja simplificada na origem). Cache dos
GeoJSON em raw/ibge/malhas/. O codigo IBGE (codarea) vira o codigo TSE do municipio,
que e a chave de todos os JSONs do site (municipios_2026.parquet traz os dois).

Saidas: docs/dados/geo/br.json (UFs) e docs/dados/geo/{UF}.json (municipios), TopoJSON
com propriedade `id` = sigla da UF ou codigo TSE do municipio.

Uso:  .venv/Scripts/python -m web.geo
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import topojson as tp

from sintetico.caminhos import BRUTO_IBGE, SAIDA

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "docs" / "dados" / "geo"
CACHE = BRUTO_IBGE / "malhas"
API = "https://servicodados.ibge.gov.br/api/v3/malhas"
COD_UF = {"RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17, "MA": 21, "PI": 22,
          "CE": 23, "RN": 24, "PB": 25, "PE": 26, "AL": 27, "SE": 28, "BA": 29, "MG": 31, "ES": 32,
          "RJ": 33, "SP": 35, "PR": 41, "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53}
UF_DE_COD = {str(v): k for k, v in COD_UF.items()}


def baixa(url: str, destino: Path) -> dict:
    if destino.exists():
        return json.loads(destino.read_text("utf-8"))
    r = requests.get(url, timeout=120, headers={"Accept": "application/vnd.geo+json"})
    r.raise_for_status()
    corpo = r.content
    if corpo[:2] == b"\x1f\x8b":
        corpo = gzip.decompress(corpo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(corpo)
    return json.loads(corpo)


def topo(gdf: gpd.GeoDataFrame, simpl: float) -> dict:
    t = tp.Topology(gdf[["id", "geometry"]], prequantize=1e5, topoquantize=2e4,
                    toposimplify=simpl, object_name="a")
    return json.loads(t.to_json())


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    mun = pd.read_parquet(SAIDA / "municipios_2026.parquet").dropna(subset=["cd_ibge"])
    tse = dict(zip(mun["cd_ibge"].astype(str), mun["cd_mun"].astype(int)))

    br = baixa(f"{API}/paises/BR?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF",
               CACHE / "br_uf.geojson")
    g = gpd.GeoDataFrame.from_features(br["features"])
    g["id"] = g["codarea"].astype(str).map(UF_DE_COD)
    out = topo(g, 0.02)
    (DESTINO / "br.json").write_text(json.dumps(out, separators=(",", ":")), "utf-8")
    print(f"br.json {len(g)} UFs  {(DESTINO / 'br.json').stat().st_size / 1e3:.0f} KB")

    total, orfaos = 0, []
    for uf, cod in COD_UF.items():
        j = baixa(f"{API}/estados/{cod}?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=municipio",
                  CACHE / f"{uf}.geojson")
        g = gpd.GeoDataFrame.from_features(j["features"])
        g["id"] = g["codarea"].astype(str).map(tse)
        orfaos += [(uf, c) for c in g.loc[g["id"].isna(), "codarea"]]
        g = g.dropna(subset=["id"])
        g["id"] = g["id"].astype(int)
        out = topo(g, 0.002)
        arq = DESTINO / f"{uf}.json"
        arq.write_text(json.dumps(out, separators=(",", ":")), "utf-8")
        total += arq.stat().st_size
        falta = set(mun.loc[mun["uf"] == uf, "cd_mun"]) - set(g["id"])
        print(f"{uf}: {len(g):4d} municipios  {arq.stat().st_size / 1e3:5.0f} KB"
              + (f"  sem poligono: {sorted(falta)}" if falta else ""))
    print(f"total UFs: {total / 1e6:.1f} MB; codigos IBGE sem par TSE: {orfaos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
