/* Carregamento com cache e a camada ao vivo.
 *
 * Dados.json(caminho)        base estatica (docs/dados/...), cacheada
 * Dados.live(caminho)        ao vivo: tenta ?live=<url> e cai para dados/live do Pages
 */
(function () {
  "use strict";
  const cache = new Map();
  const params = new URLSearchParams(location.search);
  const LIVE_EXTRA = params.get("live");          // ex.: https://xxx.trycloudflare.com/dados/live

  async function json(caminho) {
    if (cache.has(caminho)) return cache.get(caminho);
    const p = fetch("dados/" + caminho).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    cache.set(caminho, p);
    return p;
  }

  async function live(caminho) {
    const bases = [];
    if (LIVE_EXTRA) bases.push(LIVE_EXTRA.replace(/\/$/, ""));
    bases.push("dados/live");
    for (const b of bases) {
      try {
        const r = await fetch(`${b}/${caminho}?t=${Date.now()}`, { cache: "no-store" });
        if (r.ok) return await r.json();
      } catch (e) { /* tenta a proxima base */ }
    }
    return null;
  }

  window.Dados = { json, live, temLiveExtra: !!LIVE_EXTRA };
})();
