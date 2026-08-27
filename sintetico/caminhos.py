"""Caminhos do projeto sintetico. Dados pesados ficam fora do repo (D:)."""
from __future__ import annotations

from pathlib import Path

DADOS = Path(r"D:\Claude\eleicoes-dados")
BRUTO_TSE = DADOS / "raw" / "dadosabertos"
BRUTO_IBGE = DADOS / "raw" / "ibge"
BASELINE = DADOS / "baseline"
SAIDA = DADOS / "sintetico"

UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
       "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
       "SE", "SP", "TO"]

REGIAO = {"N": ["AC", "AM", "AP", "PA", "RO", "RR", "TO"],
          "NE": ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
          "CO": ["DF", "GO", "MS", "MT"],
          "SE": ["ES", "MG", "RJ", "SP"],
          "S": ["PR", "RS", "SC"]}
UF_REGIAO = {uf: reg for reg, ufs in REGIAO.items() for uf in ufs}
