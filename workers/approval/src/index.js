// LINE Webhook受信 Worker（SPEC 8章・唯一のJS部品・以後保守不要の想定）。
// 署名検証 → postback(approve/reject)をKVに書き込み。却下直後のテキストを理由として紐付ける。

async function verifySignature(secret, body, signatureHeader) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  const expected = btoa(String.fromCharCode(...new Uint8Array(mac)));
  return expected === signatureHeader;
}

function parsePostbackData(data) {
  const params = new URLSearchParams(data);
  return { action: params.get("action"), videoId: params.get("video_id") };
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("ok");

    const body = await request.text();
    const signature = request.headers.get("x-line-signature") || "";
    if (!(await verifySignature(env.LINE_CHANNEL_SECRET, body, signature))) {
      return new Response("invalid signature", { status: 401 });
    }

    const payload = JSON.parse(body);
    for (const event of payload.events || []) {
      const userId = event.source && event.source.userId;

      // 管理者userId取得用のデバッグキー（初回セットアップ時のみ使用。以後は無害）。
      if (userId) {
        await env.APPROVAL_KV.put("debug:last_event_user_id", userId);
      }

      if (event.type === "postback") {
        const { action, videoId } = parsePostbackData(event.postback.data);
        if (!videoId || !action) continue;
        const status = action === "approve" ? "approved" : "rejected";
        await env.APPROVAL_KV.put(`video:${videoId}`, JSON.stringify({ status }));
        if (status === "rejected" && userId) {
          await env.APPROVAL_KV.put(`pending_reason:${userId}`, videoId);
        }
      } else if (event.type === "message" && event.message.type === "text" && userId) {
        const pendingVideoId = await env.APPROVAL_KV.get(`pending_reason:${userId}`);
        if (pendingVideoId) {
          const key = `video:${pendingVideoId}`;
          const current = JSON.parse((await env.APPROVAL_KV.get(key)) || "{}");
          current.reason = event.message.text;
          await env.APPROVAL_KV.put(key, JSON.stringify(current));
          await env.APPROVAL_KV.delete(`pending_reason:${userId}`);
        }
      }
    }

    return new Response("ok");
  },
};
