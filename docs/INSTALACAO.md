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
