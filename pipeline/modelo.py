"""Modelo da noite: projeta o resultado final a partir das secoes ja apuradas.

A ideia central e uma so: uma secao apurada nao vale pelo voto dela, vale pelo que ela
revela sobre as secoes parecidas que ainda nao chegaram. "Parecida" e medida pelo eixo
esquerda-direita do 2o turno ANTERIOR -- em 2026 sera 2022; aqui, para prever 2022 sem
olhar a resposta, e 2018.

  m_i  = margem da secao i na eleicao que esta sendo apurada (esq - dir, sobre validos)
  z_i  = margem da MESMA secao no 2o turno anterior  (a ancora geografica)

  m_i ~= alfa_uf + beta * z_i

`beta` e o quanto a geografia antiga ainda explica a nova; `alfa_uf` e o deslocamento
daquele estado. Os dois sao estimados SO nas secoes ja apuradas e aplicados nas que faltam,
com o peso de cada secao que falta estimado pelo eleitorado apto (que se conhece de antemao)
vezes o comparecimento observado no estado.

Encolhimento (shrinkage) em tudo: com 200 secoes apuradas nao da para confiar num beta
proprio, entao ele e puxado para 1 (swing uniforme) e o alfa do estado e puxado para o
nacional. Sem isso o modelo delira nos primeiros minutos -- que e exatamente quando ele
mais importa.

Uso:  .venv/Scripts/python -m pipeline.modelo
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:\Claude\eleicoes-dados\baseline")
CHAVE = ["uf", "cd_municipio", "zona", "secao"]

# forca dos priores, em unidades de "peso de dados equivalente".
# beta e puxado para 1 (swing uniforme); alfa_uf e puxado para o alfa nacional.
K_BETA = 0.02      # fracao da dispersao total do eixo
K_ALFA = 0.004     # fracao do eleitorado nacional
K_GAMA = 0.02      # idem, para o tamanho da secao


def monta() -> pd.DataFrame:
    """Junta: voto de 2022 (o que sera apurado), eixo de 2018 (a ancora) e o carimbo de chegada."""
    atual = pd.read_parquet(BASE / "presidente_secao_2022.parquet")
    ancora = pd.read_parquet(BASE / "presidente_secao_2018.parquet")
    quando = pd.read_parquet(BASE / "carimbos_presidente_2022_t1.parquet")

    dois18 = ancora["t2_esq"] + ancora["t2_dir"]
    ancora = ancora.assign(z=((ancora["t2_esq"] - ancora["t2_dir"]) / dois18.where(dois18 > 0)),
                           peso18=dois18)[CHAVE + ["z", "peso18"]]

    df = atual.merge(quando[CHAVE + ["aptos", "prim_tot"]], on=CHAVE, how="inner")
    df = df.merge(ancora, on=CHAVE, how="left")

    # Fallback de ancora: secao que nao existia em 2018 (7% do eleitorado) herda a media
    # do municipio, depois a da UF. Sem isso, um sexto do pais entraria como "sem ancora".
    for nivel in (["uf", "cd_municipio"], ["uf"]):
        med = (df.dropna(subset=["z"]).groupby(nivel)
               .apply(lambda g: np.average(g["z"], weights=g["peso18"]), include_groups=False)
               .rename("z_fb").reset_index())
        df = df.merge(med, on=nivel, how="left")
        df["z"] = df["z"].fillna(df["z_fb"])
        df = df.drop(columns="z_fb")
    df["z"] = df["z"].fillna(0.0)

    # Tamanho da secao: existe sinal real (swing de +0,177 nas grandes contra +0,067 nas
    # pequenas), e ele ajuda nos primeiros 20 minutos -- mas PIORA de 2% apurado em diante
    # (erro de +0,68 contra +0,37 na metade da apuracao). Com uma noite so de validacao,
    # manter uma variavel que ajuda numa janela de 20 min e convite a overfitting.
    # Fica implementada e DESLIGADA por padrao; reavaliar quando houver mais noites.
    df["s"] = np.log(df["aptos"].clip(lower=1))
    df["m"] = (df["t1_esq"] - df["t1_dir"]) / df["validos_t1"].where(df["validos_t1"] > 0)
    df["v"] = df["validos_t1"].astype(float)
    df = df.dropna(subset=["m", "prim_tot"]).sort_values("prim_tot").reset_index(drop=True)
    return df


def projeta(df: pd.DataFrame, n: int, com_tamanho: bool = False) -> dict:
    """Projecao com as primeiras `n` secoes apuradas. Nada depois de `n` e olhado."""
    ap, falta = df.iloc[:n], df.iloc[n:]
    if len(ap) < 2 or ap["v"].sum() <= 0:
        return {}

    w, m = ap["v"].to_numpy(), ap["m"].to_numpy()
    sb = float(np.average(df["s"], weights=df["v"]))          # centro fixo: nao muda com a amostra
    X = np.column_stack([ap["z"].to_numpy(), ap["s"].to_numpy() - sb]) if com_tamanho         else ap["z"].to_numpy()[:, None]
    b0 = np.array([1.0, 0.0])[: X.shape[1]]                   # prior: swing uniforme, sem efeito de tamanho

    xb = np.average(X, axis=0, weights=w)
    Xc, mb = X - xb, np.average(m, weights=w)
    A = (Xc * w[:, None]).T @ Xc
    b = (Xc * w[:, None]).T @ (m - mb)
    K = np.diag([K_BETA * float(df["v"].sum() * df["z"].var()),
                 K_GAMA * float(df["v"].sum() * df["s"].var())][: X.shape[1]])
    coef = np.linalg.solve(A + K, b + K @ b0)
    beta = float(coef[0])

    # alfa nacional e por UF, o do estado encolhido para o nacional
    resid = m - X @ coef
    alfa_nac = float(np.average(resid, weights=w))
    k_a = K_ALFA * float(df["aptos"].sum())
    g = pd.DataFrame({"uf": ap["uf"].to_numpy(), "w": w, "r": resid}).groupby("uf")
    soma = g.apply(lambda x: pd.Series({"sw": x["w"].sum(), "swr": (x["w"] * x["r"]).sum()}),
                   include_groups=False)
    alfa_uf = ((soma["swr"] + k_a * alfa_nac) / (soma["sw"] + k_a)).to_dict()

    # comparecimento por UF, para estimar o peso das secoes que faltam
    taxa_nac = float(ap["v"].sum() / ap["aptos"].sum())
    tx = g.apply(lambda x: pd.Series({"a": 0.0}), include_groups=False)  # placeholder p/ indice
    t = pd.DataFrame({"uf": ap["uf"].to_numpy(), "v": w, "ap": ap["aptos"].to_numpy()}).groupby("uf").sum()
    taxa_uf = ((t["v"] + k_a * taxa_nac) / (t["ap"] + k_a)).to_dict()

    if len(falta):
        a_f = falta["uf"].map(alfa_uf).fillna(alfa_nac).to_numpy()
        Xf = np.column_stack([falta["z"].to_numpy(), falta["s"].to_numpy() - sb])             if com_tamanho else falta["z"].to_numpy()[:, None]
        m_f = a_f + Xf @ coef
        v_f = falta["aptos"].to_numpy() * falta["uf"].map(taxa_uf).fillna(taxa_nac).to_numpy()
    else:
        m_f = v_f = np.zeros(0)

    num = float((w * m).sum() + (v_f * m_f).sum())
    den = float(w.sum() + v_f.sum())
    return {
        "n": n, "pct_secoes": 100 * n / len(df),
        "hora": ap["prim_tot"].iloc[-1],
        "naive": 100 * float((w * m).sum() / w.sum()),
        "modelo": 100 * num / den,
        "beta": beta, "alfa_nac": alfa_nac,
    }


def main() -> None:
    df = monta()
    final = 100 * float((df["v"] * df["m"]).sum() / df["v"].sum())
    print(f"secoes: {len(df):,}   margem final real: {final:+.2f}")
    print()
    print("   hora     apurado     tela    so eixo  +tamanho |  erro tela  erro eixo  erro c/tam")
    for p_ in [0.1, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30, 50, 70, 90]:
        n = max(2, int(len(df) * p_ / 100))
        r = projeta(df, n, com_tamanho=True)
        r0 = projeta(df, n, com_tamanho=False)
        if not r:
            continue
        print(f"  {r['hora']:%H:%M:%S}   {r['pct_secoes']:5.1f}%  {r['naive']:+7.2f}  "
              f"{r0['modelo']:+8.2f}  {r['modelo']:+8.2f} | {r['naive']-final:+8.2f} "
              f"{r0['modelo']-final:+10.2f} {r['modelo']-final:+11.2f}")

if __name__ == "__main__":
    main()
