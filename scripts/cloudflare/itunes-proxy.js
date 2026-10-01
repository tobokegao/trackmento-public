/**
 * TRACKMENTO — iTunes Search APIの中継（Cloudflare Workers）
 *
 * 注意（2026-09-12確認）: Cloudflare Workersの送信元IPは多数の利用者で共有されており、Appleはそれも
 * 「Rate limit has been exceeded」（429）で制限する。そのためWorkers経由では解決しない。
 * 専用IPを持つホスト（VPSなど）に同じ中継を置く場合の参考実装として残す。
 *
 * Appleは共有ホスティング（Renderなど）のIPを403/429で遮断することがある。このWorkerを経由すると
 * CloudflareのIPからAppleを呼べる。サーバー（backend/sources/itunes.py）はITUNES_PROXY_URLが設定されていると
 * https://itunes.apple.com/searchの代わりに <ITUNES_PROXY_URL>/searchを呼ぶ。
 *
 * 設定手順（Cloudflareダッシュボード）
 *   1. Workers & Pages → Create → Create Worker → 名前（例trackmento-itunes）→ Deploy
 *   2. Edit code → この内容を貼り付けてDeploy
 *   3. （任意・推奨）Settings → Variables and Secrets → 変数TOKENに長いランダム文字列を設定 → Deploy
 *   4. WorkerのURL（https://trackmento-itunes.<アカウント>.workers.dev）をRenderの環境変数ITUNES_PROXY_URLに、
 *      TOKENの値をITUNES_PROXY_TOKENに設定 → 再デプロイ
 *   確認: Renderのログで `[itunes] 403` が出なくなり、/healthのitunes_proxyがtrue
 *
 * 無料枠は1日10万リクエスト。応答は10分間Cloudflare側でキャッシュされるので、同じ検索はAppleまで行かない。
 */
const UPSTREAM = "https://itunes.apple.com/search";
const ALLOWED_PARAMS = ["term", "entity", "country", "limit", "media", "attribute"];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "GET" || url.pathname !== "/search") {
      return new Response("not found", { status: 404 });
    }
    // TOKENを設定した場合は、同じ値をX-Trackmento-Tokenヘッダーに付けた呼び出しだけ通す
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
      headers: { "User-Agent": "trackmento/0.1 (+https://trackmento.com)", "Accept": "application/json" },
      cf: { cacheTtl: 600, cacheEverything: true },   // 同じ検索は10分間Cloudflareのキャッシュから返す
    });
    const out = new Response(res.body, res);
    out.headers.set("Cache-Control", "public, max-age=600");
    out.headers.delete("set-cookie");
    return out;
  },
};
