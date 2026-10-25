# Apuração 2º turno 2026 — needle duplo

Cópia do [`apuracao-2026`](https://github.com/agamemnon140/apuracao-2026) (histórico preservado)
para a noite de **25/10/2026**, presidente, Lula 13 × Flávio Bolsonaro 22. **Só voto apurado**,
nenhuma pesquisa. No ar: https://agamemnon140.github.io/apuracao-2t-2026/

Dois needles, o **mesmo estimador** (`pipeline/needle_hier.py`) com duas âncoras por urna:

| | âncora de cada urna | o que mede |
|---|---|---|
| **A** | 1º turno de 2026 na mesma urna (terceiros divididos na proporção local) | quanto o 2º turno se afasta do 1º — transferência de terceiros e abstenção |
| **B** | 2º turno de 2022 andado pela demografia (`proj26` do repo original) | quanto 2026 se afasta de 2022 |

Para cada um: P(vitória), % final projetado, **votos necessários** (alvo de 50%+1 por urna,
ganho relativo igual no país — `sintetico/alvo_2026.py`), evolução no tempo, por UF e município.
Painel de **abstenção**: seções totalizadas × 1º turno 2026 × 2022 nos mesmos lugares.

Construído em 25/10/2026 entre 15h e 17h, nesta máquina, sem os dados do projeto original
(`D:\Claude\eleicoes-dados`): as âncoras foram **reconstruídas do próprio repo** por
`sintetico/ancora_repo.py --cov` (`docs/dados/sec/*.json`: `proj26`, `pr26t1`, `pf`), com 27
covariáveis (8 do perfil TSE de 2026 + 19 do sintético de 2022, casadas por seção em 92% das urnas)
e a ordem de chegada de 04/10/2026 (`pipeline/carimbos.py 2026`).

σ **medido em replays**, um por needle, feed municipal sem boletins, |erro| × 1,25 e piso de 0,5 pt:

| apurado | B: erro (replay do 1º turno 2026, ordem real) | A: erro (replay análogo 2022: 1º→2º turno) | tela crua |
|---|---|---|---|
| 0,5% | +1,9 | +0,6 | −5 / −11 |
| 1% | +1,4 | +0,1 | −5 / −9 |
| 3% | +0,9 | −0,1 | −7 / −10 |
| 5% | +0,3 | −0,2 | −8 / −10 |
| 10–90% | ≤ ±0,3 | ≤ ±0,05 | −9 … −2 |

(`probe/replay_t1_2026.py`, `probe/replay_t2_2022.py`; uma noite cada — **não é a calibração do
projeto original**, que tinha boletins e a ordem de 2022.)

## Rodar

```sh
set ELEICOES_DADOS=C:\Users\Henrique\Documents\eleicoes-dados-2t
py -m sintetico.ancora_repo --cov                             # ancoras A e B (27 covariaveis) + abst_base.json
py -m sintetico.alvo_2026 --turno 2                           # alvo B
py -m sintetico.alvo_2026 --turno 2 --ancora ancora_t1_2026.parquet --sufixo t1_2026   # alvo A
py -m probe.replay_t1_2026 --grava                            # sigma do B (replay de 04/10/2026)
py -m probe.replay_t2_2022 --grava                            # sigma do A (replay analogo de 2022)
py -m runner.ciclo2t --modo simula --ciclos 2                 # ensaio sem rede
py -m runner.coletor --descobre && py -m runner.coletor --malhas --t2
py -m runner.bu_crawler --turno 2                             # janela 1: boletins por urna
py -m runner.ciclo2t --modo ao-vivo --publicar pages          # janela 2: o laco
py -m tools.serve_docs                                        # janela 3: http://localhost:8000
```

Saídas em `docs/dados/`: `live/br.json` + `live/uf/{UF}.json` (B), `live_t1/...` (A),
`live/historico.json` (um ponto por ciclo), `live/abstencao.json`. O painel antigo do 1º turno
ficou em `docs/painel_2022.html`; método e achados do projeto original em `docs/METODO.md` e
`probe/ACHADOS.md`.
