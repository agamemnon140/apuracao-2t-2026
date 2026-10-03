"""Estado publico de vespera: apuracao de 2026 zerada, candidatos na tela, nada de replay.

Grava docs/dados/live.json (contrato do index.html) e docs/dados/live/br.json (mapa) em
modo "aguardando": 0% apurado, paineis vazios, ancora demografica e alvo como referencia.
Apaga live/uf e live/mun de ensaios anteriores. E o que o Pages deve servir ate as 17h de
04/10; o runner da noite sobrescreve tudo no primeiro ciclo.

Uso:  .venv/Scripts/python -m runner.aguardando
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
from pathlib import Path

from sintetico.caminhos import SAIDA

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "docs" / "dados"


def main() -> int:
    alvo = json.loads((SAIDA / "alvo_2026_t1.json").read_text("utf-8"))
    cand = json.loads((RAIZ / "config" / "candidatos_2026.json").read_text("utf-8"))["presidente"]
    nomes = {"esq": cand["cands"][cand["esq"]]["nome"].title(), "dir": cand["cands"][cand["dir"]]["nome"].title(),
             "nr_esq": cand["esq"], "nr_dir": cand["dir"]}
    agora = dt.datetime.now().isoformat(timespec="seconds")
    anc_esq = round(100 * alvo["br"]["ancora_esq"], 1)
    anc_dir = round(100 * alvo["br"]["ancora_dir"], 1)
    anc_out = round(100 * alvo["br"].get("ancora_out", 0.0), 1)

    arq = DOCS / "live.json"
    live = json.loads(arq.read_text("utf-8")) if arq.exists() else {}
    live.update({
        "modo": "aguardando",
        "congelado_em": "apuração do 1º turno começa às 17h de 04/10/2026",
        "gerado_em": agora, "instante": "--:--",
        "presidente": {"lider": "—", "margem": 0.0, "tela_crua": 0.0, "p_lider": 0.5,
                       "pct_secoes": 0.0, "sigma": None, "sh_esq": None, "sh_dir": None,
                       "p_esq50": None, "p_dir50": None,
                       "ancora_esq": anc_esq, "ancora_dir": anc_dir, "ancora_out": anc_out},
        "governos": [], "senado": [], "camara": None, "assembleias": None,
        "cobertura": [],
    })
    arq.write_text(json.dumps(live, ensure_ascii=False, separators=(",", ":")), "utf-8")

    (DOCS / "live").mkdir(parents=True, exist_ok=True)
    (DOCS / "live" / "br.json").write_text(json.dumps({
        "modo": "aguardando", "gerado_em": agora, "instante": "--:--:--",
        "turno": 1, "pct_secoes": 0.0, "n_bu": 0, "nomes": nomes, "pr": None, "ufs": {},
    }, ensure_ascii=False, separators=(",", ":")), "utf-8")
    for sub in ("uf", "mun"):
        shutil.rmtree(DOCS / "live" / sub, ignore_errors=True)
    print(f"estado 'aguardando' gravado (ancora {anc_esq}% x {anc_dir}% + {anc_out}% terceiros; "
          f"{nomes['esq']} {nomes['nr_esq']} x {nomes['dir']} {nomes['nr_dir']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
