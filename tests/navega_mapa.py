"""Teste de fumaca do mapa: abre docs/ num servidor local com o Edge headless, navega os
niveis e cargos, junta erros de console e tira screenshots.

Uso:  .venv/Scripts/python tests/navega_mapa.py [saida_dir] [hash ...]
"""
from __future__ import annotations

import http.server
import socketserver
import sys
import threading
from functools import partial
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[1]
PORTA = 8765

ROTEIRO = [
    ("br", ""),
    ("uf_ac", "#uf=AC&cargo=pr&turno=1"),
    ("mun_riobranco", "#uf=AC&mun=1392&cargo=pr&turno=2"),
    ("zona", "#uf=AC&mun=1392&zona=9&cargo=pr&turno=1"),
    ("local", "#uf=AC&mun=1392&zona=1&local=1031&cargo=pr&turno=1"),
    ("secao", "#uf=AC&mun=1392&zona=9&local=1368&secao=11&cargo=pr&turno=1"),
    ("gov", "#uf=AC&mun=1392&cargo=gov&turno=1"),
    ("sen", "#uf=AC&cargo=sen&turno=1"),
    ("depf", "#uf=AC&mun=1392&cargo=df&turno=1"),
    ("eixo", "#uf=AC&cargo=pr&turno=1&eixo=1"),
]


def main() -> int:
    saida = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "tests" / "shots"
    saida.mkdir(parents=True, exist_ok=True)
    roteiro = ROTEIRO if len(sys.argv) <= 2 else [(f"extra{k}", h) for k, h in enumerate(sys.argv[2:])]
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(RAIZ / "docs"))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", PORTA), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    erros = []
    with sync_playwright() as p:
        nav = p.chromium.launch(channel="msedge", headless=True)
        for largura, sufixo in [(1360, ""), (390, "_mobile")]:
            pg = nav.new_page(viewport={"width": largura, "height": 1000})
            pg.on("console", lambda m: erros.append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None)
            pg.on("pageerror", lambda e: erros.append(f"[pageerror] {e}"))
            for nome, h in (roteiro if not sufixo else roteiro[:3]):
                pg.goto(f"http://127.0.0.1:{PORTA}/mapa.html{h}")
                pg.wait_for_timeout(2500)
                pg.screenshot(path=str(saida / f"{nome}{sufixo}.png"), full_page=True)
                titulo = pg.text_content("#titulo-unidade")
                print(f"{nome}{sufixo}: {titulo!r}")
            pg.close()
        nav.close()
    srv.shutdown()
    print("\n".join(erros) if erros else "sem erros de console")
    # 404 de live/ (antes da noite) e favicon sao esperados; so erro de JavaScript reprova
    return 1 if any("pageerror" in e for e in erros) else 0


if __name__ == "__main__":
    sys.exit(main())
