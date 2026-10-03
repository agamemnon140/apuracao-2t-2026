/* Bolhas: um ponto por eleitor (ou por N eleitores), em grade, categoria apos categoria.
 *
 * Bolhas.escala(totais, dotMax) -> {porPonto, colunas}   mesma escala para os dois paineis
 * Bolhas.desenha(canvas, cats, escala) -> hit(x, y) -> categoria | null
 *   cats: [{nome, cor, n}]  (n = eleitores; cor = CSS)
 */
(function () {
  "use strict";
  const ASPECTO = 0.72;                 // altura / largura desejada da grade

  function escala(totais, dotMax) {
    const t = Math.max(1, ...totais.map((x) => x || 0));
    const porPonto = Math.max(1, Math.ceil(t / dotMax));
    const pontos = Math.ceil(t / porPonto);
    const colunas = Math.max(8, Math.ceil(Math.sqrt(pontos / ASPECTO)));
    return { porPonto, colunas, pontosMax: pontos };
  }

  function desenha(canvas, cats, esc) {
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.parentElement.clientWidth || 300;
    const cols = esc.colunas;
    const s = W / cols;
    // pontos por categoria (arredondamento que preserva o total)
    let acum = 0, acumPts = 0;
    const faixas = [];
    for (const c of cats) {
      acum += c.n || 0;
      const fim = Math.round(acum / esc.porPonto);
      faixas.push({ ini: acumPts, fim, cat: c });
      acumPts = fim;
    }
    const rowsMax = Math.ceil(esc.pontosMax / cols);
    const H = Math.max(s * rowsMax, 40);
    canvas.style.height = H + "px";
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const r = s * 0.40;
    const quadrado = s < 4;
    for (const f of faixas) {
      ctx.fillStyle = f.cat.cor;
      ctx.beginPath();
      for (let k = f.ini; k < f.fim; k++) {
        const x = (k % cols) * s + s / 2, y = Math.floor(k / cols) * s + s / 2;
        if (quadrado) ctx.rect(x - s * 0.45, y - s * 0.45, s * 0.9, s * 0.9);
        else { ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, Math.PI * 2); }
      }
      ctx.fill();
    }
    return function hit(px, py) {
      const k = Math.floor(py / s) * cols + Math.floor(px / s);
      if (px < 0 || px >= W) return null;
      for (const f of faixas) if (k >= f.ini && k < f.fim) return f.cat;
      return null;
    };
  }

  window.Bolhas = { escala, desenha };
})();
