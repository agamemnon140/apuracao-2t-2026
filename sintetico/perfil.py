"""Agrega o perfil do eleitorado por secao (TSE) nos eixos sexo, idade e escolaridade.

Entrada: perfil_eleitor_secao_2022_{UF}.zip (uma linha por secao x genero x estado civil
x faixa etaria x grau de instrucao, com QT_ELEITORES_PERFIL).

Faixa etaria vem como codigo NNMM (limite inferior nos dois primeiros digitos); o limite
inferior basta para as faixas do modelo. Codigos negativos (#NE) ficam fora do denominador
do eixo correspondente, mas contam no total de eleitores.

Saida: sintetico/perfil_secao_2022.parquet -- uma linha por secao.

Uso:  .venv/Scripts/python -m sintetico.perfil
"""
from __future__ import annotations

import csv
import io
import sys
import time
import zipfile

import pandas as pd

from .caminhos import BRUTO_TSE, SAIDA, UFS

# indices do acumulador
(ELEITORES, MASC, FEM, ID_1624, ID_2539, ID_4059, ID_60M, ID_VAL,
 ESC_FUND, ESC_MEDIO, ESC_SUP, ESC_VAL) = range(12)


def acumula_uf(uf: str, acc: dict) -> int:
    z = zipfile.ZipFile(BRUTO_TSE / "2022" / "perfil_secao" / f"perfil_eleitor_secao_2022_{uf}.zip")
    n = 0
    with z.open(f"perfil_eleitor_secao_2022_{uf}.csv") as fh:
        rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
        for r in rd:
            q = int(r["QT_ELEITORES_PERFIL"])
            if not q:
                continue
            chave = (uf, int(r["CD_MUNICIPIO"]), int(r["NR_ZONA"]), int(r["NR_SECAO"]))
            a = acc.get(chave)
            if a is None:
                a = acc[chave] = [0] * 12
            a[ELEITORES] += q
            g = r["CD_GENERO"]
            if g == "2":
                a[MASC] += q
            elif g == "4":
                a[FEM] += q
            fx = int(r["CD_FAIXA_ETARIA"])
            if fx > 0:
                idade = fx // 100
                a[ID_VAL] += q
                if idade < 25:
                    a[ID_1624] += q
                elif idade < 40:
                    a[ID_2539] += q
                elif idade < 60:
                    a[ID_4059] += q
                else:
                    a[ID_60M] += q
            esc = int(r["CD_GRAU_ESCOLARIDADE"])
            if esc > 0:
                a[ESC_VAL] += q
                if esc <= 4:
                    a[ESC_FUND] += q
                elif esc <= 6:
                    a[ESC_MEDIO] += q
                else:
                    a[ESC_SUP] += q
            n += 1
    return n


def main() -> int:
    acc: dict = {}
    for uf in UFS:
        t0 = time.time()
        n = acumula_uf(uf, acc)
        print(f"{uf}: {n} linhas, {len(acc)} secoes acumuladas [{time.time() - t0:.0f}s]", flush=True)

    df = pd.DataFrame([(k[0], k[1], k[2], k[3], *v) for k, v in acc.items()],
                      columns=["uf", "cd_municipio_tse", "zona", "secao", "eleitores",
                               "masc", "fem", "id_1624", "id_2539", "id_4059", "id_60m",
                               "id_val", "esc_fund", "esc_medio", "esc_sup", "esc_val"])
    sexo_val = df["masc"] + df["fem"]
    df["pct_fem"] = df["fem"] / sexo_val.where(sexo_val > 0)
    for c in ["id_1624", "id_2539", "id_4059", "id_60m"]:
        df[f"pct_{c[3:]}"] = df[c] / df["id_val"].where(df["id_val"] > 0)
    for c in ["esc_fund", "esc_medio", "esc_sup"]:
        df[f"pct_{c[4:]}"] = df[c] / df["esc_val"].where(df["esc_val"] > 0)

    fora = ["masc", "fem", "id_1624", "id_2539", "id_4059", "id_60m", "id_val",
            "esc_fund", "esc_medio", "esc_sup", "esc_val"]
    df = df.drop(columns=fora)
    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / "perfil_secao_2022.parquet"
    df.to_parquet(destino, index=False)
    print(f"{len(df)} secoes, gravado {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
