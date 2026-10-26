import json
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

S = "C:/Users/Henrique/AppData/Local/Temp/claude/C--Users-Henrique/12f2fc25-eb46-4286-90f4-10c26e647ab9/scratchpad"
cum = pd.read_csv(f"{S}/curva_contrafactual.csv", parse_dates=["hora"])
j = json.load(open(f"{S}/pontos_reais_2t.json"))
pts = pd.DataFrame(j["pts"], columns=["t", "pct", "lula"])
pts["h"] = pts.t.str.slice(0, 2).astype(int) + pts.t.str.slice(3, 5).astype(int) / 60
cum["h"] = cum.hora.dt.hour + cum.hora.dt.minute / 60 + cum.hora.dt.second / 3600
FIN2, FIN1 = 51.78, 48.98
COR_CF, COR_1T, COR_2T = "#7d3c98", "#d35400", "#1e8449"

fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5.6), dpi=150)
for ax in (a1, a2):
    ax.axhline(50, color="#999", ls="--", lw=1)
    ax.axhline(FIN2, color=COR_2T, ls=":", lw=1.2)
    ax.axhline(FIN1, color=COR_1T, ls=":", lw=1.2)
    ax.set_ylim(40, 58)
    ax.grid(alpha=.25)
    ax.set_ylabel("Lula, % dos votos nos dois (acumulado)")

a1.plot(cum.pct, cum.cf2, color=COR_CF, lw=2.2, label="2º turno, se contado na ORDEM DO 1º TURNO (contrafactual)")
a1.plot(cum.pct, cum.real1, color=COR_1T, lw=1.6, label="1º turno (04/10), ordem real")
a1.plot(pts.pct[pts.pct < 20], pts.lula[pts.pct < 20], "o-", color=COR_2T, ms=3.5, lw=1.2, label="2º turno (25/10), tela oficial como aconteceu")
a1.plot(pts.pct[pts.pct > 90], pts.lula[pts.pct > 90], "o-", color=COR_2T, ms=3.5, lw=1.2)
a1.plot([pts.pct[pts.pct < 20].iloc[-1], pts.pct[pts.pct > 90].iloc[0]], [pts.lula[pts.pct < 20].iloc[-1], pts.lula[pts.pct > 90].iloc[0]], ls=":", color=COR_2T, lw=1)
a1.set_xlim(0, 100)
a1.set_xlabel("% das seções totalizadas")
a1.set_title("Por % apurado", fontsize=11)
a1.text(99, FIN2 + .25, f"final 2T {FIN2:.2f}", ha="right", va="bottom", fontsize=8, color=COR_2T)
a1.text(99, FIN1 - .25, f"final 1T {FIN1:.2f}", ha="right", va="top", fontsize=8, color=COR_1T)
a1.legend(loc="lower right", fontsize=8, framealpha=.95)

ct = cum[cum.pct >= 0.3]
a2.plot(ct.h, ct.cf2, color=COR_CF, lw=2.2, label="contrafactual (relógio de 04/10)")
a2.plot(ct.h, ct.real1, color=COR_1T, lw=1.6, label="1º turno real (relógio de 04/10)")
antes, depois = pts[pts.h < 20.5], pts[pts.h >= 20.5]
a2.plot(antes.h, antes.lula, "o-", color=COR_2T, ms=3.5, lw=1.2, label="2º turno real (relógio de 25/10)")
a2.plot(depois.h, depois.lula, "o-", color=COR_2T, ms=3.5, lw=1.2)
a2.plot([antes.h.iloc[-1], depois.h.iloc[0]], [antes.lula.iloc[-1], depois.lula.iloc[0]], ls=":", color=COR_2T, lw=1)
a2.set_xlim(17, 22.6)
a2.set_xticks(range(17, 23))
a2.set_xticklabels([f"{h}h" for h in range(17, 23)])
a2.set_xlabel("hora do dia")
a2.set_title("Por hora", fontsize=11)
a2.annotate("19h56–21h40: máquina em\nsuspensão, sem registro", xy=(20.9, 50.9), fontsize=7.5, color="#555", ha="center")
a2.legend(loc="lower right", fontsize=8, framealpha=.95)

fig.suptitle("Como a apuração do 2º turno teria aparecido se as urnas entrassem na mesma ordem do 1º turno", fontsize=12.5)
fig.text(0.5, 0.005, "Contrafactual: voto do 1º turno por seção + swing do município (log-odds) = 2º turno sintético por seção, acumulado na ordem real de chegada de 04/10/2026 "
         "(carimbos dos dados abertos). Tela real do 2º turno: totais oficiais do TSE registrados pelo laço a cada minuto (19h14–19h56 e 21h40–22h23).",
         ha="center", fontsize=7.5, color="#444", wrap=True)
fig.tight_layout(rect=(0, 0.04, 1, 0.95))
fig.savefig(f"{S}/contrafactual.png")
print("ok")
