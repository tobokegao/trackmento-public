/**
 * TRACKMENTO — iTunes Search API の中継（Cloudflare Workers）
 *
 * 注意（2026-09-12 確認）: Cloudflare Workers の送信元 IP は多数の利用者で共有されており、Apple はそれも
 * 「Rate limit has been exceeded」（429）で制限する。そのため Workers 経由では解決しない。
 * 専用 IP を持つホスト（VPS など）に同じ中継を置く場合の参考実装として残す。
 *
 * Apple は共有ホスティング（Render など）の IP を 403/429 で遮断することがある。この Worker を経由すると
 * Cloudflare の IP から Apple を呼べる。サーバー（backend/sources/itunes.py）は ITUNES_PROXY_URL が設定されていると
 * https://itunes.apple.com/search の代わりに <ITUNES_PROXY_URL>/search を呼ぶ。
 *
 * 設定手順（Cloudflare ダッシュボード）
 *   1. Workers & Pages → Create → Create Worker → 名前（例 trackmento-itunes）→ Deploy
 *   2. Edit code → この内容を貼り付けて Deploy
 *   3. （任意・推奨）Settings → Variables and Secrets → 変数 TOKEN に長いランダム文字列を設定 → Deploy
 *   4. Worker の URL（https://trackmento-itunes.<アカウント>.workers.dev）を Render の環境変数 ITUNES_PROXY_URL に、
 *      TOKEN の値を ITUNES_PROXY_TOKEN に設定 → 再デプロイ
 *   確認: Render のログで `[itunes] 403` が出なくなり、/health の itunes_proxy が true
 *
 * 無料枠は 1 日 10 万リクエスト。応答は 10 分間 Cloudflare 側でキャッシュされるので、同じ検索は Apple まで行かない。
 */
const UPSTREAM = "https://itunes.apple.com/search";
const ALLOWED_PARAMS = ["term", "entity", "country", "limit", "media", "attribute"];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "GET" || url.pathname !== "/search") {
      return new Response("not found", { status: 404 });
    }
    // TOKEN を設定した場合は、同じ値を X-Trackmento-Token ヘッダーに付けた呼び出しだけ通す
    if (env.TOKEN && request.headers.get("X-Trackmento-Token") !== env.TOKEN) {
      return new Response("forbidden", { status: 403 });
    }
    const upstream = new URL(UPSTREAM);
    for (const k of ALLOWED_PARAMS) {
      const v = url.searchParams.get(k);
      if (v) upstream.searchParams.set(k, v.slice(0, 300));
    }
    if (!upstream.searchParams.get("term")) {
      return new Response('{"resultCount":0,"results":[]}', { headers: { "content-type": "application/json" } });
    }
    const res = await fetch(upstream.toString(), {
      headers: { "User-Agent": "trackmento/0.1 (+https://trackmento.onrender.com)", "Accept": "application/json" },
      cf: { cacheTtl: 600, cacheEverything: true },   // 同じ検索は 10 分間 Cloudflare のキャッシュから返す
    });
    const out = new Response(res.body, res);
    out.headers.set("Cache-Control", "public, max-age=600");
    out.headers.delete("set-cookie");
    return out;
  },
};
