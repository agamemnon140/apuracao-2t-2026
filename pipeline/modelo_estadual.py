"""Modelo da noite para cargo estadual -- onde o candidato NAO tem historico proprio.

No presidente da para ancorar cada secao no que ela votou na eleicao anterior para o mesmo
cargo. Num governo isso nao existe: o candidato de 2022 nao estava na cedula de 2018. O que
sobrevive entre ciclos e a **geografia**: a posicao de cada secao no eixo esquerda-direita
medido pelo 2o turno presidencial anterior.

Entao, para cada candidato c, o modelo estima AO VIVO -- so com as secoes ja apuradas -- como
o voto dele varia com esse eixo:

    share_c(i) ~= a_c + b_c * z_i

e projeta nas secoes que faltam. `a_c` e `b_c` nascem do zero a cada eleicao; `b_c` e
encolhido para 0 (sem inclinacao geografica) enquanto ha pouca apuracao, senao um punhado de
secoes de um reduto define a curva inteira do candidato.

Uso:  .venv/Scripts/python -m pipeline.modelo_estadual [UF]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:\Claude\eleicoes-dados\baseline")
CHAVE = ["uf", "cd_municipio", "zona", "secao"]
K_B = 0.05          # forca do prior b_c = 0, em fracao da dispersao total do eixo
MARCOS = [0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30, 50, 70, 90]


def eixo_2018() -> pd.DataFrame:
    """Posicao de cada secao no eixo esquerda-direita do 2o turno de 2018."""
    a = pd.read_parquet(BASE / "presidente_secao_2018.parquet")
    dois = a["t2_esq"] + a["t2_dir"]
    return a.assign(z=(a["t2_esq"] - a["t2_dir"]) / dois.where(dois > 0),
                    peso18=dois)[CHAVE + ["z", "peso18"]]


def monta(uf: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devolve (secoes com carimbo e peso, matriz secao x candidato em votos)."""
    votos = pd.read_parquet(BASE / "governador_secao_2022_t1.parquet")
    votos = votos[(votos["uf"] == uf) & votos["candidato"]]
    car = pd.read_parquet(BASE / "carimbos_governador_2022_t1.parquet")
    car = car[car["uf"] == uf]

    wide = (votos.pivot_table(index=CHAVE, columns="nr_votavel", values="votos",
                              aggfunc="sum", fill_value=0).reset_index())
    sec = car[CHAVE + ["aptos", "prim_tot"]].merge(wide, on=CHAVE, how="inner")
    sec = sec.merge(eixo_2018(), on=CHAVE, how="left")
    for nivel in (["cd_municipio"], []):
        if sec["z"].isna().any():
            if nivel:
                med = (sec.dropna(subset=["z"]).groupby(nivel)
                       .apply(lambda g: np.average(g["z"], weights=g["peso18"]), include_groups=False)
                       .rename("fb").reset_index())
                sec = sec.merge(med, on=nivel, how="left")
                sec["z"] = sec["z"].fillna(sec["fb"]); sec = sec.drop(columns="fb")
            else:
                sec["z"] = sec["z"].fillna(sec["z"].mean())
    cands = [c for c in wide.columns if c not in CHAVE]
    sec["validos"] = sec[cands].sum(axis=1)
    sec = sec[sec["validos"] > 0].sort_values("prim_tot").reset_index(drop=True)
    return sec, cands


def projeta(sec: pd.DataFrame, cands: list[str], n: int) -> pd.Series:
    """Share final projetado de cada candidato, vendo so as primeiras `n` secoes."""
    ap, falta = sec.iloc[:n], sec.iloc[n:]
    w = ap["validos"].to_numpy(dtype=float)
    if w.sum() <= 0:
        return pd.Series(dtype=float)
    z = ap["z"].to_numpy()
    zb = float(np.average(z, weights=w))
    szz = float((w * (z - zb) ** 2).sum())
    k = K_B * float(sec["validos"].sum() * sec["z"].var())

    # peso estimado das secoes que faltam: eleitorado apto x comparecimento observado
    taxa = float(w.sum() / ap["aptos"].sum()) if ap["aptos"].sum() > 0 else 0.0
    v_f = falta["aptos"].to_numpy(dtype=float) * taxa
    z_f = falta["z"].to_numpy()

    out = {}
    for c in cands:
        y = (ap[c].to_numpy(dtype=float) / w)
        yb = float(np.average(y, weights=w))
        szy = float((w * (z - zb) * (y - yb)).sum())
        b = (szy + k * 0.0) / (szz + k) if (szz + k) > 0 else 0.0     # prior b = 0
        a = yb - b * zb
        y_f = np.clip(a + b * z_f, 0, 1)
        out[c] = float((w * y).sum() + (v_f * y_f).sum())
    s = pd.Series(out)
    return s / s.sum()


def avalia(uf: str) -> dict:
    sec, cands = monta(uf)
    final = sec[cands].sum() / sec[cands].sum().sum()
    ordem = final.sort_values(ascending=False)
    campeao, dupla = ordem.index[0], set(ordem.index[:2])

    hist = []
    for p in MARCOS:
        n = max(5, int(len(sec) * p / 100))
        pr = projeta(sec, cands, n)
        if pr.empty:
            continue
        o = pr.sort_values(ascending=False)
        hist.append({"pct": 100 * n / len(sec), "hora": sec["prim_tot"].iloc[n - 1],
                     "lider_ok": o.index[0] == campeao, "dupla_ok": set(o.index[:2]) == dupla,
                     "erro_lider": 100 * (pr[campeao] - final[campeao])})
    # a partir de quando o lider projetado nunca mais erra
    quando = next((h for i, h in enumerate(hist) if all(x["lider_ok"] for x in hist[i:])), None)
    dupla_q = next((h for i, h in enumerate(hist) if all(x["dupla_ok"] for x in hist[i:])), None)
    return {"uf": uf, "n_cands": len(cands), "campeao": campeao,
            "lider_desde": quando, "dupla_desde": dupla_q, "hist": hist}


def main() -> None:
    ufs = [sys.argv[1].upper()] if len(sys.argv) > 1 else sorted(
        pd.read_parquet(BASE / "governador_secao_2022_t1.parquet")["uf"].unique())
    print("  UF  cands   lider certo desde        dupla de 2o turno certa desde   erro do lider ali")
    for uf in ufs:
        try:
            r = avalia(uf)
        except Exception as e:
            print(f"  {uf}   ERRO {type(e).__name__}: {e}")
            continue
        l, d = r["lider_desde"], r["dupla_desde"]
        sl = f"{l['hora']:%H:%M} ({l['pct']:4.1f}%)" if l else "nunca estabiliza"
        sd = f"{d['hora']:%H:%M} ({d['pct']:4.1f}%)" if d else "nunca estabiliza"
        er = f"{l['erro_lider']:+6.2f}" if l else "     -"
        print(f"  {uf}    {r['n_cands']:>2}   {sl:<22}  {sd:<28}  {er}")


if __name__ == "__main__":
    main()
