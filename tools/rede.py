"""Cliente HTTP da noite: cabecalhos de navegador, conexao persistente, retry com backoff.

Desde ago/2026 o Akamai do TSE exige o conjunto completo de cabecalhos de navegador
(sec-ch-ua + Sec-Fetch-*). Para o feed de resultados imitamos o XHR do app oficial
(Referer do app, Sec-Fetch-Mode: cors). Uma Session por thread: reaproveita TLS.

  get(url) -> (status, bytes)      nunca levanta; -1 = erro de rede
  get_json(url) -> (status, obj|None)
"""
from __future__ import annotations

import json
import random
import threading
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0")
XHR = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Microsoft Edge";v="126"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Referer": "https://resultados.tse.jus.br/oficial/app/index.html",
}
_local = threading.local()


def sessao() -> requests.Session:
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update(XHR)
        a = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=8, max_retries=0)
        s.mount("https://", a)
        _local.s = s
    return s


def get(url: str, timeout: float = 20, tentativas: int = 3) -> tuple[int, bytes]:
    """(status, corpo). 404 volta na hora (resposta valida). 429/5xx/rede: backoff exponencial."""
    st, corpo = -1, b""
    for i in range(tentativas):
        try:
            r = sessao().get(url, timeout=timeout)
            st, corpo = r.status_code, (r.content if r.status_code == 200 else b"")
        except requests.RequestException as e:
            st, corpo = -1, str(e).encode("utf-8", "replace")
        if st in (200, 404, 403):
            return st, corpo
        time.sleep(min(30.0, (2 ** i)) * (0.5 + random.random()))
    return st, corpo


def get_json(url: str, timeout: float = 20, tentativas: int = 3):
    st, corpo = get(url, timeout, tentativas)
    if st != 200:
        return st, None
    try:
        return st, json.loads(corpo.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return -2, None
