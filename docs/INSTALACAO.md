# Rodar em outra máquina — instalação do zero

Meta: sair de uma máquina Windows limpa para `PRONTO PARA A NOITE` em ~20 minutos.
O que viaja: o **código** (este repo) + os **dados** (~1,1 GB, via `tools/empacota_dados`).
O `raw/` de 14 GB fica para trás — nada da noite lê os zips brutos.

## Na máquina de origem (antes de sair)

```sh
# empacota os dados num pendrive/HD (ex.: E:\eleicoes-dados)
.venv/Scripts/python -m tools.empacota_dados E:\eleicoes-dados
```

Leve também o repo: `git push` (e clone lá), ou copie a pasta `apuracao-2026` inteira
para o mesmo pendrive (sem a `.venv`, que não sobrevive à mudança de máquina).

## Na máquina nova

1. **Python 3.13** — python.org/downloads, marcar *Add python.exe to PATH*.
   (3.11+ funciona; os parquets foram escritos com pyarrow 25.)
2. **Git** — git-scm.com (só se for clonar/puxar; a cópia da pasta dispensa).
3. **Código e ambiente**:
   ```sh
   git clone https://github.com/agamemnon140/apuracao-2026.git   # ou copie a pasta
   cd apuracao-2026
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
4. **Dados**: copie a pasta do pendrive para o disco (ex.: `C:\eleicoes-dados`) e aponte:
   ```sh
   setx ELEICOES_DADOS C:\eleicoes-dados      # permanente; abra um terminal novo depois
   ```
   Sem a variável, o código procura em `D:\Claude\eleicoes-dados`.
5. **Conferir** (10 s):
   ```sh
   .venv\Scripts\python -m tools.checa_preparo
   ```
   Deve terminar em `PRONTO PARA A NOITE`. Cada linha diz o que falta e como resolver.
6. **Ensaio de 2 minutos** (replay de 2022 congelado a ~10% + volta ao estado de véspera):
   ```sh
   .venv\Scripts\python -m runner.ciclo --modo replay --turno 1 --velocidade 1 --inicio 18:32 --intervalo 5 --ciclos 1 --lag 2
   .venv\Scripts\python -m runner.aguardando
   .venv\Scripts\python -m http.server 8000 -d docs     # abrir http://localhost:8000/mapa.html
   ```

7. **Opcional — deputado por seção** (painel candidato × urna no modo local/túnel;
   não vai ao Pages): `py -m web.gera_estatico --depsec` (~5 min, 666 MB em `docs/dados/depsec/`),
   ou copie essa pasta junto com o repo.

## Quais dados são esses, exatamente

`tools/empacota_dados.py` copia (e `tools/checa_preparo.py` confere) tudo o que a noite lê:

| Pasta/arquivo | Tamanho | O que é | Se faltar |
|---|---|---|---|
| `sintetico/ancora_2026.parquet` | 36 MB | a âncora: 2022 por urna + deriva demográfica | precondição de tudo |
| `sintetico/alvo_2026_t1.*` (`_t2`) | 60 MB | alvo de 50%+1 por urna | mapa/needle sem alvo |
| `sintetico/` demais | ~420 MB | pred/base/universo (regenerações e 2º turno) | só para refazer âncora/alvo |
| `baseline/calib_*.json` | <1 MB | incertezas calibradas (sigma, k_p, ESS) | needle sem probabilidade |
| `baseline/*.parquet` | ~460 MB | 2018/2022 por seção + carimbos | replay de teste e deputados-replay |
| `live/config_2026.json`, `cm-*.json`, `cs/3220/` | 12 MB | códigos do pleito 3220 e malhas de 2026 | o coletor rebaixa em ~2 min com internet |
| `ferramentas/cloudflared.exe` | 55 MB | túnel (plano B de publicação) | só o túnel |
| `ele-c.retrato.json` | <1 MB | memória do vigia do índice | nada crítico |

**Na noite, nada mais é baixado além do feed do TSE** (coletor e crawler baixam sozinhos).
O `raw/` (14 GB de zips do TSE/IBGE) só serve para RECONSTRUIR as bases do zero — não leve.

**Sem pendrive?** Rode o empacotador para uma pasta e compacte-a num zip para subir ao seu drive:
```sh
.venv\Scripts\python -m tools.empacota_dados D:\Claude	ransporte\eleicoes-dados
tar -a -c -f D:\Claude	ransporte\dados-noite.zip -C D:\Claude	ransporte eleicoes-dados
```
ou rode o empacotador direto para uma pasta sincronizada (Drive/OneDrive). ~1,1 GB.

**Reconstruir do zero** (horas; só se os dados se perderem): `sintetico/baixa.py` e
`tools/baixa_baseline.py` baixam os brutos públicos (TSE dados abertos + IBGE, ~6 GB), e a
ordem de regeneração está no topo do `RUNBOOK.md` (projecao_2026 → ancora → alvo → gera_estatico),
com os baselines em `pipeline/baseline_*.py` e `pipeline/carimbos.py`. Não é plano para véspera.

## O que mais a noite precisa

- **Internet** (feed do TSE e crawler de boletins). Hotspot de celular como plano B de IP.
- **Publicar no Pages** (`runner.ciclo --publicar pages`) exige credencial do GitHub na
  máquina: `git push` tem de funcionar sem senha (Git Credential Manager loga no primeiro
  push, ou `gh auth login`). Teste ANTES das 17h.
- **Túnel** (plano B, dispensa GitHub): `cloudflared.exe` já vai na pasta `ferramentas/`
  dos dados.
- **Opcional, só para testes visuais**: Microsoft Edge instalado (o teste de fumaça
  `tests/navega_mapa.py` dirige o Edge via Playwright).

## O dia, em ordem

`docs/RUNBOOK.md` é o roteiro da noite. Resumo: `checa_preparo` → (se o índice mudou)
`runner.coletor --descobre` e `--malhas` → 16h30: `runner.bu_crawler` numa janela,
`runner.ciclo --modo ao-vivo --turno 1 --publicar pages` na outra.
A configuração de 2026 já está descoberta e empacotada: ciclo `ele2026`, pleito `3220`,
eleições `6257` (presidente) e `6259` (estaduais).
