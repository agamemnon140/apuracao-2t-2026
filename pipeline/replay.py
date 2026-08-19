"""Re-toca a noite de 2022 exatamente como aconteceu, e confere contra o registro oficial.

Junta o QUE cada secao votou (`presidente_secao_2022.parquet`) com QUANDO ela entrou
(`carimbos_presidente_2022_t1.parquet`) e acumula na ordem real. Se a curva reconstruida
bater com `Historico_Totalizacao_Presidente_BR_1T_2022`, a cadeia inteira -- chave de secao,
carimbo, agregacao -- esta correta. Se nao bater, e melhor descobrir agora.

Uso:  .venv/Scripts/python -m pipeline.replay
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd

BASE = Path(r"D:\Claude\eleicoes-dados\baseline")
BRUTO = Path(r"D:\Claude\eleicoes-dados\raw\dadosabertos")
CHAVE = ["uf", "cd_municipio", "zona", "secao"]
MARCOS = [0.5, 1, 2, 5, 10, 20, 30, 50, 70, 90, 100]


def oficial() -> pd.DataFrame:
    """A curva publicada pelo TSE, para conferencia."""
    nome = "Historico_Totalizacao_Presidente_BR_1T_2022"
    z = zipfile.ZipFile(BRUTO / f"{nome}.zip")
    txt = z.read(f"{nome}.csv").decode("latin-1")
    rows = list(csv.DictReader(io.StringIO(txt), delimiter=";"))
    col = {k.strip(): k for k in rows[0]}
    f = lambda r, c: float(r[col[c]].strip().replace(",", ".") or 0)   # noqa: E731
    return pd.DataFrame({
        "pct": [100 * f(r, "PE_SECOES_TOT_ACUMULADO") for r in rows],
        "esq": [f(r, "LULA_QT_VOTOS_TOT_ACUMULADO") for r in rows],
        "dir": [f(r, "JAIR_BOLSONARO_QT_VOTOS_TOT_ACUMULADO") for r in rows],
        "conc": [f(r, "QT_VOTOS_CONCORRENTES_ACUMULADO") for r in rows],
    })


def main() -> None:
    votos = pd.read_parquet(BASE / "presidente_secao_2022.parquet")
    quando = pd.read_parquet(BASE / "carimbos_presidente_2022_t1.parquet")
    df = quando.merge(votos, on=CHAVE, how="left", indicator=True)

    orfas = (df["_merge"] != "both").sum()
    print(f"secoes com carimbo: {len(quando):,}   com voto casado: {len(df) - orfas:,}   orfas: {orfas:,}")
    df = df[df["_merge"] == "both"].sort_values("prim_tot").reset_index(drop=True)

    df["c_esq"] = df["t1_esq"].cumsum()
    df["c_dir"] = df["t1_dir"].cumsum()
    df["c_conc"] = df["validos_t1"].cumsum()
    df["c_pct"] = 100 * (df.index + 1) / len(quando)

    of = oficial()
    fesq, fdir, fconc = df["c_esq"].iloc[-1], df["c_dir"].iloc[-1], df["c_conc"].iloc[-1]
    print(f"\nfinal reconstruido:  esq {fesq:,.0f}  dir {fdir:,.0f}  concorrentes {fconc:,.0f}")
    print(f"final oficial:       esq {of['esq'].iloc[-1]:,.0f}  dir {of['dir'].iloc[-1]:,.0f}  "
          f"concorrentes {of['conc'].iloc[-1]:,.0f}")

    print("\n  apurado   margem reconstruida   margem oficial   diferenca")
    for m in MARCOS:
        i = df["c_pct"].searchsorted(m)
        if i >= len(df):
            i = len(df) - 1
        r = df.iloc[i]
        mr = 100 * (r["c_esq"] - r["c_dir"]) / r["c_conc"] if r["c_conc"] else 0
        j = of["pct"].searchsorted(m)
        j = min(j, len(of) - 1)
        o = of.iloc[j]
        mo = 100 * (o["esq"] - o["dir"]) / o["conc"] if o["conc"] else 0
        print(f"  {m:5.1f}%        {mr:+8.2f}          {mo:+8.2f}       {mr - mo:+6.2f}")


if __name__ == "__main__":
    main()
