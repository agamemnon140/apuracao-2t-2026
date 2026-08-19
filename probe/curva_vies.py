"""A curva do vies de composicao, medida no historico oficial de totalizacao de 2022.

O TSE publica `Historico_Totalizacao_Presidente_BR_{1T,2T}_2022.zip`: a trajetoria
segundo a segundo da apuracao presidencial, com votos acumulados por candidato. E o
unico registro publico de parciais que existe -- e so para presidente, so em 2022
(2014, 2018 e 2024 nao tem).

Este script mede quanto erraria quem simplesmente lesse o numero da tela. Esse erro e
exatamente o que o modelo da noite precisa corrigir.
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import cdn  # noqa: E402

DADOS = Path(r"D:\Claude\eleicoes-dados\raw\dadosabertos")
BASE = f"{cdn.CDN}/eleicoes/eleicoes2022"
ALVOS = [0.5, 1, 2, 5, 10, 20, 30, 50, 70, 90]


def carrega(turno: str) -> list[dict]:
    nome = f"Historico_Totalizacao_Presidente_BR_{turno}_2022"
    z = zipfile.ZipFile(cdn.baixa(f"{BASE}/{nome}.zip", DADOS / f"{nome}.zip"))
    txt = z.read(f"{nome}.csv").decode("latin-1")
    return list(csv.DictReader(io.StringIO(txt), delimiter=";"))


def relatorio(turno: str, a: str, b: str) -> None:
    rows = carrega(turno)
    col = {k.strip(): k for k in rows[0]}
    def f(r, c): return float(r[col[c]].strip().replace(",", ".") or 0)

    fim = rows[-1]
    tot = f(fim, "QT_VOTOS_CONCORRENTES_ACUMULADO")
    FA, FB = 100 * f(fim, f"{a}_QT_VOTOS_TOT_ACUMULADO") / tot, 100 * f(fim, f"{b}_QT_VOTOS_TOT_ACUMULADO") / tot
    print(f"\n=== {turno} de 2022 — final: {a.title()} {FA:.2f}% x {FB:.2f}% {b.title()} "
          f"(margem {FA - FB:+.2f}) ===")
    print("  apurado   hora       margem na tela   erro")
    i = 0
    for alvo in ALVOS:
        while i < len(rows) and 100 * f(rows[i], "PE_SECOES_TOT_ACUMULADO") < alvo:
            i += 1
        if i >= len(rows):
            break
        r = rows[i]
        c = f(r, "QT_VOTOS_CONCORRENTES_ACUMULADO")
        if c <= 0:
            continue
        m = 100 * (f(r, f"{a}_QT_VOTOS_TOT_ACUMULADO") - f(r, f"{b}_QT_VOTOS_TOT_ACUMULADO")) / c
        print(f"  {alvo:5.1f}%   {r[col['DT_TOTALIZACAO']].strip()[-8:]}   {m:+8.1f}        {m - (FA - FB):+6.1f} pontos")


if __name__ == "__main__":
    relatorio("1T", "LULA", "JAIR_BOLSONARO")
    relatorio("2T", "LULA", "JAIR_BOLSONARO")
