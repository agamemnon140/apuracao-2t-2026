"""Baixa os brutos que o sintetico precisa e ainda nao estao em disco.

TSE: locais de votacao (coordenadas) e perfil do eleitorado por secao.
IBGE: malha de setores 2022 (gpkg, 1,5 GB), agregados por setor (basico,
cor/raca, demografia, renda do responsavel) e PIB dos Municipios.

Retomavel: baixa para .part com Range e renomeia no fim; arquivo presente e pulado.
Desde ago/2026 o Akamai do TSE (cdn/www/dadosabertos) exige o conjunto completo de
headers de navegador (sec-ch-ua + Sec-Fetch-*); so o prefixo Mozilla/5.0 devolve 403.

Uso:  .venv/Scripts/python -m sintetico.baixa
"""
from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request

from .caminhos import BRUTO_IBGE, BRUTO_TSE, UFS

NAVEGADOR = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Microsoft Edge";v="126"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

TSE_CDN = "https://cdn.tse.jus.br/estatistica/sead/odsele"
IBGE = "https://ftp.ibge.gov.br"
AGREG = f"{IBGE}/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios"

ALVOS = [
    (f"{TSE_CDN}/eleitorado_locais_votacao/eleitorado_local_votacao_2022.zip",
     BRUTO_TSE / "2022" / "eleitorado_local_votacao_2022.zip"),
    (f"{AGREG}/malha_com_atributos/setores/gpkg/BR/BR_setores_CD2022.gpkg",
     BRUTO_IBGE / "BR_setores_CD2022.gpkg"),
    (f"{AGREG}/Agregados_por_Setor_csv/Agregados_por_setores_basico_BR_20260520.zip",
     BRUTO_IBGE / "Agregados_por_setores_basico_BR.zip"),
    (f"{AGREG}/Agregados_por_Setor_csv/Agregados_por_setores_cor_ou_raca_BR.zip",
     BRUTO_IBGE / "Agregados_por_setores_cor_ou_raca_BR.zip"),
    (f"{AGREG}/Agregados_por_Setor_csv/Agregados_por_setores_demografia_BR.zip",
     BRUTO_IBGE / "Agregados_por_setores_demografia_BR.zip"),
    (f"{IBGE}/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/"
     "Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip",
     BRUTO_IBGE / "Agregados_por_setores_renda_responsavel_BR.zip"),
    (f"{IBGE}/Pib_Municipios/2021/base/base_de_dados_2010_2021_txt.zip",
     BRUTO_IBGE / "pib_municipios_2010_2021_txt.zip"),
] + [
    (f"{TSE_CDN}/perfil_eleitor_secao/perfil_eleitor_secao_2022_{uf}.zip",
     BRUTO_TSE / "2022" / "perfil_secao" / f"perfil_eleitor_secao_2022_{uf}.zip")
    for uf in UFS
]


def baixa(url: str, destino) -> str:
    if destino.exists():
        return "ja em disco"
    destino.parent.mkdir(parents=True, exist_ok=True)
    part = destino.with_suffix(destino.suffix + ".part")
    ja = part.stat().st_size if part.exists() else 0
    headers = dict(NAVEGADOR)
    if ja:
        headers["Range"] = f"bytes={ja}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            modo = "ab" if ja and r.status == 206 else "wb"
            with open(part, modo) as fh:
                while True:
                    bloco = r.read(1 << 20)
                    if not bloco:
                        break
                    fh.write(bloco)
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:
        return f"erro: {e}"
    part.rename(destino)
    return f"ok ({destino.stat().st_size / 1e6:.1f} MB)"


def main() -> int:
    falhas = 0
    for url, destino in ALVOS:
        t0 = time.time()
        r = baixa(url, destino)
        print(f"{destino.name:60s} {r}  [{time.time() - t0:.0f}s]", flush=True)
        if r.startswith(("HTTP", "erro")):
            falhas += 1
    print(f"concluido, {falhas} falha(s)", flush=True)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
