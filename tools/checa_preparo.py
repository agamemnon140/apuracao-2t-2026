"""Checagem de prontidao para a noite: ambiente, dados, configuracao e TSE.

Roda em ~10 s e diz se ESTA maquina consegue rodar o needle agora. Para usar em outra
maquina: clone o repo, crie o venv (requirements.txt), copie os dados (tools/empacota_dados)
e rode isto.

Uso:  .venv/Scripts/python -m tools.checa_preparo
"""
from __future__ import annotations

import importlib
import json
import sys
import time

OK, FALHA, AVISO = "[ ok ]", "[FALHA]", "[aviso]"
problemas = 0


def diz(nivel: str, texto: str) -> None:
    global problemas
    if nivel == FALHA:
        problemas += 1
    print(f"{nivel} {texto}")


def main() -> int:
    global problemas
    v = sys.version_info
    diz(OK if v >= (3, 11) else FALHA, f"Python {v.major}.{v.minor}.{v.micro} (precisa 3.11+; testado em 3.13)")

    for mod, fatal in [("pandas", True), ("numpy", True), ("pyarrow", True), ("requests", True),
                       ("sklearn", False), ("geopandas", False), ("playwright", False)]:
        try:
            m = importlib.import_module(mod)
            diz(OK, f"{mod} {getattr(m, '__version__', '')}")
        except ImportError:
            diz(FALHA if fatal else AVISO,
                f"{mod} ausente" + ("" if fatal else " (so para regenerar ancora/geo/testes)"))

    from sintetico.caminhos import BASELINE, DADOS, FERRAMENTAS, SAIDA, VIVO
    diz(OK if DADOS.exists() else FALHA, f"dados em {DADOS} (mude com ELEICOES_DADOS)")
    arquivos = [
        (SAIDA / "ancora_2026.parquet", True), (SAIDA / "alvo_2026_t1.json", True),
        (SAIDA / "alvo_2026_t1.parquet", True), (BASELINE / "calib_presidente.json", True),
        (BASELINE / "calib_estadual_hier.json", True), (BASELINE / "calib_federal.json", True),
        (SAIDA / "ancora_2022_calib.parquet", False), (BASELINE / "presidente_secao_2022.parquet", False),
        (FERRAMENTAS / "cloudflared.exe", False),
    ]
    for arq, fatal in arquivos:
        existe = arq.exists()
        diz(OK if existe else (FALHA if fatal else AVISO),
            f"{arq.relative_to(DADOS)}" + ("" if existe else " AUSENTE" + ("" if fatal else " (replay/tunel)")))

    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1]
    for rel in ["config/partidos.json", "config/candidatos_2026.json", "docs/dados/meta.json",
                "docs/dados/br.json"]:
        diz(OK if (raiz / rel).exists() else FALHA, rel)

    cfg = VIVO / "config_2026.json"
    if cfg.exists():
        c = json.loads(cfg.read_text("utf-8"))
        t1 = c.get("turnos", {}).get("1", {})
        diz(OK, f"config 2026: ciclo {c.get('ciclo')} pleito {t1.get('pleito')} "
                f"eleicoes {[e['ele'] for e in t1.get('eleicoes', [])]}")
        n_cs = len(list((VIVO / "cs" / str(t1.get("pleito"))).glob("*.json"))) if t1.get("pleito") else 0
        diz(OK if n_cs >= 27 else AVISO, f"malha de secoes (cs): {n_cs} UFs (runner.coletor --malhas)")
    else:
        diz(AVISO, "live/config_2026.json ausente: rode runner.coletor --descobre")

    try:
        from tools.rede import get_json
        t0 = time.time()
        st, j = get_json("https://resultados.tse.jus.br/oficial/comum/config/ele-c.json?t=%d" % time.time())
        diz(OK if st == 200 else FALHA,
            f"TSE ele-c.json: HTTP {st} em {time.time() - t0:.1f}s" + (f" (gerado {j.get('dg')})" if j else ""))
    except Exception as e:
        diz(FALHA, f"rede ate o TSE: {e}")

    # a cadeia inteira importa?
    for mod in ["pipeline.needle_hier", "pipeline.estadual_live", "pipeline.dep_live",
                "runner.coletor", "runner.bu_crawler", "runner.ciclo", "runner.aguardando"]:
        try:
            importlib.import_module(mod)
            diz(OK, f"import {mod}")
        except Exception as e:
            diz(FALHA, f"import {mod}: {e}")

    print("\n" + ("PRONTO PARA A NOITE" if problemas == 0 else f"{problemas} problema(s) acima"))
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
