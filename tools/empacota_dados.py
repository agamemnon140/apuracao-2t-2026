"""Empacota os dados da noite para levar a outra maquina (pendrive, HD, rede).

Copia de ELEICOES_DADOS (default D:\\Claude\\eleicoes-dados) apenas o que o modelo usa:
  baseline/    parquets de 2018/2022 e calibracoes (~410 MB)
  sintetico/   ancora, alvo, pred, universo 2026 (~320 MB)
  ferramentas/ cloudflared.exe (~55 MB)
  live/        config_2026.json, malhas cm/cs ja baixadas (NAO leva feed/bu de ensaios)
  ele-c.retrato.json

O raw/ (14 GB) fica de fora: nada da noite le os zips brutos. Na outra maquina, aponte
ELEICOES_DADOS para a pasta copiada (ou copie para D:\\Claude\\eleicoes-dados).

Uso:  .venv/Scripts/python -m tools.empacota_dados E:\\eleicoes-dados [--so-listar]
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from sintetico.caminhos import DADOS

ITENS = [
    ("baseline", "dir"),
    ("sintetico", "dir"),
    ("ferramentas", "dir"),
    ("live/config_2026.json", "arq"),
    ("live/cm-6257.json", "arq"),
    ("live/cm-6259.json", "arq"),
    ("live/cs", "dir"),
    ("ele-c.retrato.json", "arq"),
]


def tamanho(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    so_listar = "--so-listar" in sys.argv
    if not args and not so_listar:
        print(__doc__)
        return 1
    total = 0
    plano = []
    for rel, tipo in ITENS:
        src = DADOS / rel
        if not src.exists():
            print(f"  (ausente, pulado) {rel}")
            continue
        t = tamanho(src)
        total += t
        plano.append((src, rel, tipo, t))
        print(f"  {t / 1e6:8.1f} MB  {rel}")
    print(f"  {'-' * 8}\n  {total / 1e6:8.1f} MB no total")
    if so_listar:
        return 0
    destino = Path(args[0])
    destino.mkdir(parents=True, exist_ok=True)
    for src, rel, tipo, t in plano:
        dst = destino / rel
        print(f"copiando {rel} ({t / 1e6:.0f} MB)...", flush=True)
        if tipo == "dir":
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    print(f"pronto: {destino}  (na outra maquina: set ELEICOES_DADOS={destino})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
