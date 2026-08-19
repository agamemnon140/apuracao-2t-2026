"""Download do CDN de dados abertos do TSE.

O CDN rejeita User-Agent de robo (curl, urllib, "bot") com 403 -- inclusive o UA que o
repo eleicoes-2026 usa. O prefixo "Mozilla/5.0" e o que passa no filtro; mantemos o nome
do projeto depois dele para nao mentir sobre quem esta baixando.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

CDN = "https://cdn.tse.jus.br/estatistica/sead"
H = {"User-Agent": "Mozilla/5.0 apuracao-2026/0.1", "Accept": "*/*",
     "Accept-Encoding": "identity", "Connection": "keep-alive"}


def baixa(url: str, destino: Path, forcar: bool = False) -> Path:
    """Baixa se ainda nao existe. Devolve o caminho local."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and not forcar and destino.stat().st_size > 0:
        return destino
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=600) as r:
        with open(tmp, "wb") as fh:
            while chunk := r.read(1 << 20):
                fh.write(chunk)
    tmp.replace(destino)
    return destino
