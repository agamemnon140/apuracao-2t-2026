"""Alvo de vitoria: quanto cada candidato precisa em cada lugar para fazer 50%+1 dos VALIDOS.

Parte da ancora por urna (sintetico/ancora_2026.py ou sintetico/ancora_repo.py). Por urna:

  val_i  = aptos_i * sigma(a_part_i)          validos esperados (a ancora vem do 2o turno,
                                              onde validos = os dois campos)
  out_i  = val_i * sigma(a_out_i)             terceiros, ancorados no 1o turno anterior
  dois_i = val_i - out_i                      o que sobra para o confronto

O alvo supoe um ganho RELATIVO igual no pais inteiro: o mesmo deslocamento `delta` em
log-odds do confronto em toda urna, escolhido por bissecao para que

  sum_i dois_i * sigma(+-(a_ed_i + delta))  =  (0,5 + 1/sum val) * sum_i val_i

ou seja, 50% dos validos + 1 voto -- terceiros contam no denominador. Log-odds porque um
ganho de 3 pontos num reduto de 80% nao e o mesmo esforco que 3 pontos num lugar de 50%.
No 2o turno nao ha terceiros (out = 0) e a conta vira a classica dois-a-dois.

Saidas (SAIDA = eleicoes-dados/sintetico):
  alvo_{sufixo}_t{1,2}.parquet  chave da urna, v_esp (validos), ancora_esq/_dir e alvo_esq/_dir
                                (fatias dos VALIDOS da propria urna), sh_out
  alvo_{sufixo}_t{1,2}.json     deltas, agregados por BR, UF e municipio

Uso:  .venv/Scripts/python -m sintetico.alvo_2026 [--turno 2] [--calib]
                                                  [--ancora ancora_t1_2026.parquet --sufixo t1_2026]
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from .ancora_2026 import CHAVE, sig
from .caminhos import SAIDA


def resolve_delta(a: np.ndarray, dois: np.ndarray, alvo_votos: float) -> float:
    """delta tal que sum(dois * sigma(a + delta)) == alvo_votos (bissecao, monotona)."""
    lo, hi = -6.0, 6.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if (dois * sig(a + mid)).sum() < alvo_votos:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def agrega(df: pd.DataFrame, por: list[str]) -> pd.DataFrame:
    g = df.assign(_ae=df["v_esp"] * df["ancora_esq"], _ad=df["v_esp"] * df["ancora_dir"],
                  _te=df["v_esp"] * df["alvo_esq"], _td=df["v_esp"] * df["alvo_dir"],
                  _o=df["v_esp"] * df["sh_out"])
    g = g.groupby(por).agg(aptos=("aptos", "sum"), v_esp=("v_esp", "sum"), _ae=("_ae", "sum"),
                           _ad=("_ad", "sum"), _te=("_te", "sum"), _td=("_td", "sum"), _o=("_o", "sum"))
    out = pd.DataFrame({"aptos": g["aptos"], "v_esp": g["v_esp"].round(0)})
    for c, s in [("ancora_esq", "_ae"), ("ancora_dir", "_ad"), ("alvo_esq", "_te"),
                 ("alvo_dir", "_td"), ("sh_out", "_o")]:
        out[c] = (g[s] / g["v_esp"]).round(5)
    return out


def _arg(nome: str, padrao: str | None) -> str | None:
    if nome in sys.argv:
        return sys.argv[sys.argv.index(nome) + 1]
    return padrao


def main() -> int:
    turno = 2 if _arg("--turno", "1") == "2" else 1
    calib = "--calib" in sys.argv
    arq_anc = _arg("--ancora", "ancora_2022_calib.parquet" if calib else "ancora_2026.parquet")
    sufixo = _arg("--sufixo", "2022_calib" if calib else "2026")
    anc = pd.read_parquet(SAIDA / arq_anc, columns=CHAVE + ["nr_local", "aptos", "a_ed", "a_part", "a_out"])
    a = anc["a_ed"].to_numpy(float)
    val = anc["aptos"].to_numpy(float) * sig(anc["a_part"])
    po = np.clip(sig(anc["a_out"]), 0.0, 0.85) if turno == 1 else np.zeros(len(anc))
    out = val * po
    dois = val - out
    meta = 0.5 + 1.0 / val.sum()
    alvo_votos = meta * val.sum()

    d_esq = resolve_delta(a, dois, alvo_votos)
    d_dir = resolve_delta(-a, dois, alvo_votos)
    df = anc[CHAVE + ["nr_local", "aptos"]].copy()
    df["v_esp"] = val
    df["sh_out"] = np.divide(out, val, out=np.zeros_like(val), where=val > 0)
    fr2 = np.divide(dois, val, out=np.zeros_like(val), where=val > 0)   # fatia dos dois nos validos
    df["ancora_esq"], df["ancora_dir"] = sig(a) * fr2, sig(-a) * fr2
    df["alvo_esq"], df["alvo_dir"] = sig(a + d_esq) * fr2, sig(-a + d_dir) * fr2

    br_ae = float((val * df["ancora_esq"]).sum() / val.sum())
    br_ad = float((val * df["ancora_dir"]).sum() / val.sum())
    br_out = float(out.sum() / val.sum())
    res_e = float((val * df["alvo_esq"]).sum() / val.sum()) - meta
    res_d = float((val * df["alvo_dir"]).sum() / val.sum()) - meta
    print(f"ancora {arq_anc}, turno {turno}{' (calib 2022)' if calib else ''}: validos esperados {val.sum():,.0f} "
          f"(terceiros {100 * br_out:.2f}%)")
    print(f"ancora (% dos validos): esquerda {100 * br_ae:.2f}  direita {100 * br_ad:.2f}")
    print(f"faltam para 50%+1: esquerda {100 * (meta - br_ae):+.2f} pontos  "
          f"direita {100 * (meta - br_ad):+.2f} pontos")
    print(f"delta esquerda {d_esq:+.4f}  delta direita {d_dir:+.4f}  (residuos {res_e:.1e}, {res_d:.1e})")

    uf = agrega(df, ["uf"])
    mun = agrega(df, ["uf", "cd_mun"])
    print("\nalvo por UF (fatia dos validos, %):")
    print((100 * uf[["ancora_esq", "alvo_esq", "ancora_dir", "alvo_dir"]]).round(1).T.to_string())

    suf = f"{sufixo}_t{turno}" if not calib else "2022_calib"
    df.to_parquet(SAIDA / f"alvo_{suf}.parquet", index=False)
    j = {"turno": turno, "ancora": arq_anc, "meta": meta, "delta_esq": d_esq, "delta_dir": d_dir,
         "br": {"aptos": int(df["aptos"].sum()), "v_esp": round(float(val.sum())),
                "ancora_esq": br_ae, "ancora_dir": br_ad, "ancora_out": br_out,
                "alvo_esq": meta, "alvo_dir": meta},
         "uf": {k: r.to_dict() for k, r in uf.iterrows()},
         "mun": {f"{k[1]}": r.to_dict() for k, r in mun.iterrows()}}
    (SAIDA / f"alvo_{suf}.json").write_text(json.dumps(j, ensure_ascii=False), "utf-8")
    print(f"\ngravados alvo_{suf}.parquet e .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
