"""Projecao 2026: aplica o comportamento estimado em 2022 a demografia de 2026.

Deriva demografica por municipio:
- sexo/idade/escolaridade: perfil_eleitorado_ATUAL (ago/2026) vs perfil 2022 agregado;
  o delta municipal e somado as covariaveis de cada secao (clip em [0,1]).
- religiao: tendencia linear municipal Censo 2010 -> 2022 extrapolada 4 anos.
- demais eixos: congelados em 2022.

Incumbencia NAO e estimavel com um ciclo so; entra como cenario declarado -- um
deslocamento no log-odds da direita, com a tabela de conversao para pontos nos validos.

Saida: sintetico/projecao_2026.json.

Uso:  .venv/Scripts/python -m sintetico.projecao_2026
"""
from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
import zipfile

import numpy as np
import pandas as pd

from .caminhos import BRUTO_TSE, SAIDA

ANOS_EXTRAP = 4.0 / 12.0     # fracao da janela censitaria 2010-2022 projetada ate 2026


def perfil_municipal_atual() -> pd.DataFrame:
    z = zipfile.ZipFile(BRUTO_TSE / "2026" / "perfil_eleitorado_ATUAL.zip")
    acc: dict = {}
    with z.open("perfil_eleitorado_ATUAL.csv") as fh:
        rd = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
        for r in rd:
            q = int(r["QT_ELEITORES"])
            if not q or r["SG_UF"] == "ZZ":
                continue
            k = int(r["CD_MUNICIPIO"])
            a = acc.setdefault(k, [0] * 12)
            a[0] += q
            g = r["CD_GENERO"]
            if g == "2":
                a[1] += q
            elif g == "4":
                a[2] += q
            fx = int(r["CD_FAIXA_ETARIA"])
            if fx > 0:
                idade = fx // 100
                a[3] += q
                a[4 if idade < 25 else 5 if idade < 40 else 6 if idade < 60 else 7] += q
            esc = int(r["CD_GRAU_INSTRUCAO"])
            if esc > 0:
                a[8] += q
                a[9 if esc <= 4 else 10 if esc <= 6 else 11] += q
    df = pd.DataFrame([(k, *v) for k, v in acc.items()],
                      columns=["cd_municipio_tse", "eleitores", "masc", "fem",
                               "id_val", "i1624", "i2539", "i4059", "i60m",
                               "esc_val", "fund", "medio", "sup"])
    den_s = (df["masc"] + df["fem"]).where(lambda s: s > 0)
    out = pd.DataFrame({"cd_municipio_tse": df["cd_municipio_tse"],
                        "pct_fem": df["fem"] / den_s})
    for c, tot in [("i1624", "id_val"), ("i2539", "id_val"), ("i60m", "id_val"),
                   ("fund", "esc_val"), ("sup", "esc_val")]:
        out["pct_" + c.lstrip("i") if c.startswith("i") else c] = \
            df[c] / df[tot].where(df[tot] > 0)
    out.columns = ["cd_municipio_tse", "pct_fem", "pct_1624", "pct_2539", "pct_60m",
                   "pct_fund", "pct_sup"]
    return out


def religiao_2010() -> pd.DataFrame:
    url = ("https://apisidra.ibge.gov.br/values/t/137/n6/all/v/93/p/2010"
           "/c133/0,95263,95277,2836?formato=json")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as r:
        dados = json.load(r)
    df = pd.DataFrame(dados[1:]).rename(columns={"D1C": "cd_mun", "D4C": "cat", "V": "v"})
    df["v"] = pd.to_numeric(df["v"], errors="coerce")
    largo = df.pivot_table(index="cd_mun", columns="cat", values="v", aggfunc="first")
    den = largo["0"].where(largo["0"] > 0)
    return pd.DataFrame({"cd_mun": largo.index.astype(str),
                         "ev10": (largo["95277"] / den).values,
                         "sr10": (largo["2836"] / den).values})


def main() -> int:
    with open(SAIDA / "modelo_2022.json", encoding="utf-8") as fh:
        M = json.load(fh)
    base = pd.read_parquet(SAIDA / "base_2022.parquet")

    atual = perfil_municipal_atual()
    p22 = base.groupby("cd_municipio_tse").apply(
        lambda g: pd.Series({c: np.average(g[c].fillna(g[c].mean()), weights=g["eleitores"])
                             for c in ["pct_fem", "pct_1624", "pct_2539", "pct_60m",
                                       "pct_fund", "pct_sup"]}), include_groups=False)
    delta = atual.set_index("cd_municipio_tse").sub(p22, fill_value=np.nan).dropna()
    print(f"deriva eleitorado: {len(delta)} municipios "
          f"(ex.: 60+ media {100 * delta['pct_60m'].mean():+.2f}pp, "
          f"superior {100 * delta['pct_sup'].mean():+.2f}pp)")

    rel10 = religiao_2010()
    liga = pd.read_parquet(SAIDA / "municipio_atributos_2022.parquet",
                           columns=["cd_mun", "cd_municipio_tse"]).dropna()
    liga["cd_municipio_tse"] = liga["cd_municipio_tse"].astype(int)
    rel = rel10.merge(liga, on="cd_mun", how="inner").set_index("cd_municipio_tse")

    proj = base.copy()
    for c in ["pct_fem", "pct_1624", "pct_2539", "pct_60m", "pct_fund", "pct_sup"]:
        proj[c] = (proj[c] + proj["cd_municipio_tse"].map(delta[c]).fillna(0)).clip(0, 1)
    dr_ev = (proj["pct_evangelica"] - proj["cd_municipio_tse"].map(rel["ev10"])) * ANOS_EXTRAP
    dr_sr = (proj["pct_sem_religiao"] - proj["cd_municipio_tse"].map(rel["sr10"])) * ANOS_EXTRAP
    proj["pct_evangelica"] = (proj["pct_evangelica"] + dr_ev.fillna(0)).clip(0, 1)
    proj["pct_sem_religiao"] = (proj["pct_sem_religiao"] + dr_sr.fillna(0)).clip(0, 1)
    print(f"deriva religiao: evangelicos {100 * dr_ev.mean():+.2f}pp, "
          f"sem religiao {100 * dr_sr.mean():+.2f}pp (medias simples)")

    coef = np.array(M["coef"]); inter = np.array(M["intercept"])
    mu = np.array(M["mu"]); sd = np.array(M["sd"])

    # padronizacao com mu/sd do MODELO (nao do df projetado)
    def matriz(df):
        d = df.copy()
        for reg in ["N", "NE", "CO", "S"]:
            d[f"reg_{reg}"] = (d["regiao"] == reg).astype(float)
        X = d[M["cols"]].astype(float)
        X = X.fillna(X.median(numeric_only=True))
        return (X.to_numpy() - mu) / sd

    def agrega(df, shift_dir=0.0):
        Xz = matriz(df)
        eta = Xz @ coef.T + inter
        eta[:, 1] += shift_dir
        eta -= eta.max(1, keepdims=True)
        p = np.exp(eta); p /= p.sum(1, keepdims=True)
        aptos = df["aptos"].to_numpy(float)
        tot = (p * aptos[:, None]).sum(0)
        sh = tot / tot.sum()
        return {"lula": sh[0], "bolsonaro": sh[1], "nenhum": sh[2],
                "validos_esq": sh[0] / (sh[0] + sh[1])}

    base22 = agrega(base)
    proj26 = agrega(proj)
    print(f"2022 (modelo): esquerda {100 * base22['validos_esq']:.2f}% dos validos")
    print(f"2026 (demografia): esquerda {100 * proj26['validos_esq']:.2f}% dos validos "
          f"({100 * (proj26['validos_esq'] - base22['validos_esq']):+.2f}pp)")

    cenarios = {}
    for s in [-0.30, -0.20, -0.10, 0.0, 0.10, 0.20, 0.30]:
        cenarios[f"{s:+.2f}"] = agrega(proj, shift_dir=s)

    # decomposicao: cada deriva sozinha
    so_eleitorado = base.copy()
    for c in ["pct_fem", "pct_1624", "pct_2539", "pct_60m", "pct_fund", "pct_sup"]:
        so_eleitorado[c] = proj[c]
    so_religiao = base.copy()
    for c in ["pct_evangelica", "pct_sem_religiao"]:
        so_religiao[c] = proj[c]

    saida = {"base_2022": base22, "proj_2026": proj26,
             "so_eleitorado": agrega(so_eleitorado), "so_religiao": agrega(so_religiao),
             "cenarios_incumbencia": cenarios,
             "deriva_media": {"pct_60m": float(delta["pct_60m"].mean()),
                              "pct_sup": float(delta["pct_sup"].mean()),
                              "evangelica": float(dr_ev.mean()),
                              "sem_religiao": float(dr_sr.mean())}}
    with open(SAIDA / "projecao_2026.json", "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False, indent=1)
    print("gravado projecao_2026.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
