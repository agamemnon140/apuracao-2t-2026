"""Gera o relatorio final: injeta sintetico/relatorio_dados.json no template HTML.

Saida: docs/sintetico_2022.html (versionado no repo; publicado como artifact).

Uso:  .venv/Scripts/python -m sintetico.relatorio
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .caminhos import SAIDA

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    with open(SAIDA / "relatorio_dados.json", encoding="utf-8") as fh:
        dados = fh.read().strip()
    template = (REPO / "sintetico" / "relatorio_template.html").read_text(encoding="utf-8")
    marcador = "/*__DADOS__*/null"
    if marcador not in template:
        print("marcador de dados nao encontrado no template")
        return 1
    html = template.replace(marcador, dados)
    destino = REPO / "docs" / "sintetico_2022.html"
    destino.write_text(html, encoding="utf-8")
    print(f"gravado {destino} ({destino.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
