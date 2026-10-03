# Apuração 2026 — needle ao vivo

Previsão do resultado nacional **durante a apuração** de 04/10/2026 e 25/10/2026, a partir dos
primeiros parciais publicados pelo TSE. Presidente, 27 governos, Senado, e (P2) deputado federal
e estadual.

Projeto separado do [`eleicoes-2026`](https://github.com/agamemnon140/eleicoes-2026), que projeta
a partir de **pesquisas**. Aqui a pesquisa não entra: **só voto apurado**.

## Por que existe

A ordem de apuração não é aleatória, e ler o número da tela engana. Medido no histórico oficial
de totalização de 2022 (`probe/curva_vies.py`):

| apurado | margem na tela (1º turno) | erro |
|---|---|---|
| 0,5% | Bolsonaro +6,8 | **12,1 pontos** |
| 10% | Bolsonaro +5,5 | 10,7 pontos |
| 50% | Bolsonaro +1,7 | 6,9 pontos |
| 70% | Lula +0,2 | 5,0 pontos |

O resultado final foi **Lula +5,2**. Quem olhasse a tela às 17h25 veria o segundo colocado
liderando por 7 pontos, e a liderança só se inverteu perto de 70% apurado. Corrigir esses 12
pontos de viés de composição — projetando o que falta a partir de como cada lugar votou em 2022 —
é a única razão de o projeto existir.

## Estado (27/09/2026)

Pronto para a noite, testado no replay de 2022 e com dados sintéticos de boletim:

- **Âncora única** por urna: 2º turno de 2022 andado pela demografia de 2026 (`sintetico/ancora_2026.py`).
- **Alvo** de 50%+1 dos válidos com ganho relativo igual no país, por UF, município, zona, local e
  seção (`sintetico/alvo_2026.py`).
- **Needle hierárquico** bottom-up sobre a âncora (`pipeline/needle_hier.py`), calibrado nas duas
  noites de 2022 (`probe/calibra_hier.py`); governador e Senado pelo modelo estadual
  (`pipeline/estadual_live.py`).
- **Coleta**: feed do TSE com descoberta de códigos em runtime (`runner/coletor.py`) e crawler de
  todos os boletins de urna (`runner/bu_crawler.py`, `runner/imgbu.py`).
- **Laço da noite** com modo replay (`runner/ciclo.py`) e publicação no Pages ou por túnel.
- **Mapa** (`docs/mapa.html`): Brasil → UF → município → zona → local → seção, 2022 × 2026, todos os
  cargos e turnos, uma bolha por eleitor; base gerada por `web/gera_estatico.py` e `web/geo.py`.

Como operar: [`docs/RUNBOOK.md`](docs/RUNBOOK.md). Método e números: [`docs/METODO.md`](docs/METODO.md).
Achados de cada sondagem: [`probe/ACHADOS.md`](probe/ACHADOS.md).

Dados pesados: `D:\Claude\eleicoes-dados` (fora do repo e fora do Google Drive).

## Rodar

```sh
py probe/curva_vies.py        # baixa e mede o vies de 2022
py tools/vigia_ele_c.py       # checa se 2026 ja foi configurada
py tools/baixa_baseline.py    # 6 GB, retomavel

.venv/Scripts/python -m pipeline.baseline_presidente   # baseline por secao
.venv/Scripts/python -m pipeline.carimbos              # ordem real de chegada
.venv/Scripts/python -m pipeline.replay                # confere contra o oficial

.venv/Scripts/python -m sintetico.ancora_2026          # ancora por urna (--calib: 2018->2022)
.venv/Scripts/python -m sintetico.alvo_2026            # alvo de 50%+1
.venv/Scripts/python -m probe.calibra_hier --rho 0,0.6,1   # needle no replay de 2022
.venv/Scripts/python -m web.gera_estatico              # base do mapa
.venv/Scripts/python -m runner.ciclo --modo replay --velocidade 20   # a noite de 2022, acelerada
.venv/Scripts/python tests/navega_mapa.py              # teste de fumaca do mapa (Edge headless)
```
