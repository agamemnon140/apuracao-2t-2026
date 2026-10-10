"""Gera docs/verificacao_2026.html: injeta sintetico/verificacao_2026.json no template.

O CSS base (cores, tipografia, tabelas) vem do template do relatorio do sintetico 2022 --
uma fonte so para os dois relatorios.

Uso:  .venv/Scripts/python -m sintetico.relatorio_verificacao [--turno 2]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from .caminhos import SAIDA

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    t2 = "--turno" in sys.argv and sys.argv[sys.argv.index("--turno") + 1] == "2"
    dados = (SAIDA / f"verificacao_2026{'_t2' if t2 else ''}.json").read_text("utf-8").strip()
    base = (REPO / "sintetico" / "relatorio_template.html").read_text("utf-8")
    css = re.search(r"<style>(.*?)</style>", base, re.S).group(1)
    html = (REPO / "sintetico" / "verificacao_template.html").read_text("utf-8")
    html = html.replace("/*__CSS_BASE__*/", css).replace("/*__DADOS__*/null", dados)
    destino = REPO / "docs" / f"verificacao_2026{'_t2' if t2 else ''}.html"
    destino.write_text(html, "utf-8")
    print(f"gravado {destino} ({destino.stat().st_size / 1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
