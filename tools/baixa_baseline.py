"""Baixa o baseline historico por secao (2018 e 2022) dos dados abertos do TSE.

As URLs saem do catalogo CKAN, nao de palpite de nome de arquivo -- foi assim que
descobrimos que `detalhe_votacao_secao` e um arquivo nacional unico, e nao um por UF.

Retomavel: pula o que ja esta em disco. Roda em segundo plano; sao ~10 GB.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdn  # noqa: E402

DESTINO = Path(r"D:\Claude\eleicoes-dados\raw\dadosabertos")
FAMILIAS = ("votacao_secao", "detalhe_votacao_secao")


def recursos(ano: int) -> list[tuple[str, str]]:
    u = f"https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-{ano}"
    j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=cdn.H), timeout=120).read())
    out = []
    for r in j["result"]["resources"]:
        nome = r["url"].rsplit("/", 1)[-1]
        if any(nome.startswith(f) for f in FAMILIAS):
            out.append((nome, r["url"]))
    return sorted(out)


def main() -> None:
    total_bytes = 0
    for ano in (2022, 2018):
        alvos = recursos(ano)
        print(f"[{ano}] {len(alvos)} arquivos no catalogo", flush=True)
        for i, (nome, url) in enumerate(alvos, 1):
            destino = DESTINO / str(ano) / nome
            if destino.exists() and destino.stat().st_size > 0:
                total_bytes += destino.stat().st_size
                print(f"  [{ano} {i:>2}/{len(alvos)}] ja tenho  {nome}", flush=True)
                continue
            t0 = time.time()
            try:
                cdn.baixa(url, destino)
            except Exception as e:
                print(f"  [{ano} {i:>2}/{len(alvos)}] FALHOU    {nome}  {type(e).__name__}: {e}", flush=True)
                continue
            n = destino.stat().st_size
            total_bytes += n
            print(f"  [{ano} {i:>2}/{len(alvos)}] ok        {nome}  {n/1e6:8.1f} MB  "
                  f"{time.time()-t0:5.1f}s", flush=True)
    print(f"\ntotal em disco: {total_bytes/1e9:.2f} GB", flush=True)


if __name__ == "__main__":
    main()
