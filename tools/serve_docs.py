"""Servidor local do site (docs/) com Cache-Control: no-cache.

O http.server padrao deixa o navegador reusar JS/CSS/JSON antigos sem perguntar; aqui
cada recurso e revalidado a cada carga (If-Modified-Since -> 304 quando nao mudou), entao
toda edicao aparece num F5 simples -- inclusive atraves do tunel.

Uso:  .venv/Scripts/python -m tools.serve_docs [porta]     (padrao 8000)
"""
from __future__ import annotations

import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"


class SemCache(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *a):
        pass


def main() -> int:
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    srv = ThreadingHTTPServer(("0.0.0.0", porta), partial(SemCache, directory=str(DOCS)))
    print(f"servindo {DOCS} em http://localhost:{porta} (Cache-Control: no-cache)")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
