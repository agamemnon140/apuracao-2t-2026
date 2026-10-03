# Runbook da noite — 04/10 e 25/10/2026

> Máquina nova? [`INSTALACAO.md`](INSTALACAO.md) leva do zero ao `PRONTO PARA A NOITE` em ~20 min (código + dados + `tools/checa_preparo`).

Tudo roda no PC local; o GitHub Pages só serve o que o runner publica. Comandos a partir de
`D:\Claude\apuracao-2026`, com o Python do projeto (`.venv/Scripts/python`, abaixo `py`).
Estado da noite em `D:\Claude\eleicoes-dados\live\` (config, feed bruto, boletins, logs).

## Antes (qualquer dia até 03/10)

1. **Base estática do mapa** (só se algo mudou nos dados de 2022/2026 ou nas cores):
   ```sh
   py -m sintetico.projecao_2026      # pred_2026.parquet
   py -m sintetico.ancora_2026        # âncora por urna (e --calib para o replay)
   py -m sintetico.alvo_2026          # alvo 1º turno (e --turno 2)
   py -m web.gera_estatico            # docs/dados/{meta,br,uf,mun,sec,dep}  ~5 min
   py -m web.geo                      # malhas (só se sumirem)
   ```
2. **Ensaio completo sem rede** (replay de 2022 em velocidade 20×, ~20 min):
   ```sh
   py -m runner.ciclo --modo replay --turno 1 --velocidade 20 --inicio 17:00 --intervalo 30
   py -m http.server -d docs 8000     # outra janela; abrir http://localhost:8000/mapa.html
   ```
   Depois do ensaio, volte ao estado público de véspera (apuração zerada, candidatos de
   2026 na tela): `py -m runner.aguardando`.
3. **Túnel** (plano B de publicação): o executável já está em `D:\Claude\eleicoes-dados\ferramentas\cloudflared.exe` (baixado em 27/09).
4. **Vigiar o índice do TSE**: `py tools/vigia_ele_c.py` (o workflow também checa de hora em hora
   de 01 a 04/10). Quando a eleição de 2026 aparecer:
   ```sh
   py -m runner.coletor --descobre    # grava live/config_2026.json (pleito, eleições, cargos)
   py -m runner.coletor --malhas      # cm (município→zona) e cs (zona→seção) de 2026
   ```

5. **Estado de véspera no ar**: `py -m runner.aguardando` grava a apuração zerada
   (0% apurado, âncora e alvo como referência) — é isso que o Pages serve até as 17h.

## Se o índice NÃO trouxer 2026 a tempo

Os códigos de eleição já vieram dos dados abertos: **6257** (presidente) e **6259** (estaduais).
Falta só o **pleito**, que aparece na URL do app oficial (`.../arquivo-urna/<pleito>/...`) ao abrir
qualquer boletim em resultados.tse.jus.br. Com ele:
```sh
py -m runner.coletor --manual <PLEITO>           # grava config com "manual": true
py -m runner.coletor --malhas
```

## Na noite (a partir das 16h30)

Três janelas:

```sh
# 1. crawler de boletins (todas as seções; prioriza municípios que o feed já contou)
py -m runner.bu_crawler

# 2. o laço: feed -> needle -> JSON -> push no Pages a cada >= 6 min
py -m runner.ciclo --modo ao-vivo --turno 1 --publicar pages --intervalo 60

# 3. (opcional) servidor local + túnel: needle a cada minuto e mapa até a seção
py -m http.server -d docs 8000
D:\Claude\eleicoes-dados\ferramentas\cloudflared.exe tunnel --url http://localhost:8000 --no-autoupdate
# divulgar: https://agamemnon140.github.io/apuracao-2026/mapa.html?live=https://<tunel>/dados/live
```

## O que olhar

| Onde | Sinal bom | Alarme e ação |
|---|---|---|
| log do ciclo (`live/log/ciclo_*.log`) | `% apurado` subindo, `bu=` subindo | `coleta` com muitos erros → ver `feed_atual.json`; o needle segue com o que tem |
| `live/estado_ciclo.json` | `publicacao: publicado` a cada ~6 min | `push falhou` → rede/credencial; seguir com `--publicar local` + túnel |
| crawler (`py -m runner.bu_crawler --status`) | `ok` crescendo; `N=` alto | `% de erro/bloqueio` repetido → Akamai apertou: deixar a concorrência cair sozinha; se travar, trocar de rede (hotspot) |
| `parse_erro` no status | ~0 | formato do boletim mudou: o needle segue só com o feed (erro medido 0,6–1,2 ponto aos 5–30%) |

O needle **nunca depende** do crawler: sem boletins ele usa o feed municipal com a ordem
histórica de chegada; com boletins, fica mais preciso (tabela em `METODO.md`).

**Deputados**: as bancadas (Câmara e Assembleias) recalculam a cada 5 ciclos, numa thread
(~20–50 s), só com boletins raspados. Os cards ficam "indisponível" até as 27 UFs terem
≥ 5 urnas raspadas cada — com o crawler no ritmo medido, isso resolve na primeira meia hora.

## 2º turno (25/10)

```sh
py -m sintetico.alvo_2026 --turno 2
py -m runner.coletor --descobre            # códigos do 2º turno (cdt2 no índice)
py -m runner.coletor --malhas --t2
py -m runner.bu_crawler --turno 2
py -m runner.ciclo --modo ao-vivo --turno 2 --publicar pages
```

## Depois

`live/feed/raw/` e `live/bu.sqlite` são a noite de 2026 inteira, na ordem em que chegou: viram o
replay de 2026 e a calibração para 2030. Não apagar.
