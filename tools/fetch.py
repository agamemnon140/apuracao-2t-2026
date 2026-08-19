"""Baixador minimo do TSE. Sem dependencia externa: so urllib."""
from __future__ import annotations

import gzip
import io
import json
import urllib.error
import urllib.request

UA = "apuracao-2026/0.1 (estudo academico; contato https://github.com/agamemnon140/apuracao-2t-2026)"


def get(url: str, timeout: int = 30) -> tuple[int, bytes]:
    """Devolve (status, corpo). Nao levanta em 404 -- 404 e resposta valida na sondagem."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.GzipFile(fileobj=io.BytesIO(body)).read()
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:                      # rede, timeout, DNS
        return -1, str(e).encode("utf-8", "replace")


def get_json(url: str, timeout: int = 30):
    st, body = get(url, timeout)
    if st != 200:
        return st, None
    try:
        return st, json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return st, None
