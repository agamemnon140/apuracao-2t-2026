"""Checa as fontes do TSE e atualiza SO o bloco de status do docs/dados/live.json.

Roda no GitHub Actions (diario, e a cada 5 min nos dias de eleicao) sem pandas nem modelo:
so urllib. Serve para a aba "Dados e fontes" refletir a saude real dos links todo dia, e
para detectar o momento em que a eleicao de 2026 aparece no indice do TSE.

Uso:  python tools/checa_fontes.py [caminho/do/live.json]
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UA_FEED = {"User-Agent": "apuracao-2026/0.1 (estudo academico; contato https://github.com/agamemnon140/apuracao-2t-2026)",
           "Accept": "*/*"}
# dadosabertos/cdn rejeitam UA de robo; o prefixo Mozilla/5.0 passa sem esconder quem somos
UA_CDN = {"User-Agent": "Mozilla/5.0 apuracao-2026/0.1", "Accept": "*/*", "Connection": "keep-alive"}

FONTES = [
    ("Índice de pleitos (descoberta de códigos)",
     "https://resultados.tse.jus.br/oficial/comum/config/ele-c.json",
     "De onde sai o código da eleição de 2026 — relido em runtime, nunca cravado."),
    ("Parcial nacional/UF (formato -r.json)",
     "https://resultados.tse.jus.br/oficial/ele2022/544/dados-simplificados/br/br-c0001-e000544-r.json",
     "O parcial que alimenta o needle: % de seções, votos por candidato. Testado no arquivo de 2022."),
    ("Detalhe por município (formato -e.json)",
     "https://resultados.tse.jus.br/oficial/ele2024/619/dados/sp/sp-c0011-e000619-e.json",
     "A UF inteira, município a município, em 1 requisição — se existir em 2026; o coletor detecta."),
    ("Catálogo de dados abertos (CKAN)",
     "https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-2022",
     "De onde saíram baseline por seção, carimbos de totalização e listas de eleitos."),
]


def get(url: str, timeout: int = 25) -> tuple[int, bytes]:
    h = UA_CDN if ("dadosabertos" in url or "cdn.tse" in url) else UA_FEED
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return -1, b""


def checa() -> list[dict]:
    out = []
    for nome, url, papel in FONTES:
        t0 = time.time()
        st, corpo = get(url)
        out.append({"nome": nome, "url": url, "papel": papel, "ok": st == 200, "http": st,
                    "ms": round(1000 * (time.time() - t0)), "bytes": len(corpo)})
    return out


def eleicao_2026(indice: bytes) -> dict:
    """A eleicao geral de 2026 ja esta configurada no indice do TSE?"""
    try:
        j = json.loads(indice.decode("utf-8", "replace"))
    except Exception:
        return {"configurada": False, "erro": "índice ilegível"}
    achados = []
    for p in j.get("pl", []):
        if p.get("dt", "").endswith("/10/2026"):
            for e in p.get("e", []):
                achados.append({"pleito": p["cd"], "eleicao": e["cd"], "data": p["dt"],
                                "nome": e.get("nm", "")})
    return {"configurada": bool(achados), "pleitos": achados,
            "indice_gerado_em": f"{j.get('dg', '')} {j.get('hg', '')}".strip()}


def main() -> None:
    alvo = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).resolve().parents[1] / "docs" / "dados" / "live.json"
    live = json.loads(alvo.read_text("utf-8"))
    fontes = checa()
    live["fontes"] = fontes
    live["fontes_checadas_em"] = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    st, corpo = get(FONTES[0][1])
    live["tse_2026"] = eleicao_2026(corpo) if st == 200 else {"configurada": False, "erro": f"HTTP {st}"}
    alvo.write_text(json.dumps(live, ensure_ascii=False, separators=(",", ":")), "utf-8")
    for f in fontes:
        print(("OK   " if f["ok"] else "FALHA"), f["http"], f"{f['ms']:>5} ms", f["nome"])
    print("eleição 2026 no índice:", "SIM" if live["tse_2026"].get("configurada") else "ainda não",
          live["tse_2026"].get("indice_gerado_em", ""))


if __name__ == "__main__":
    main()
