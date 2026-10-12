// Shared HTTP boundaries. This module also runs in middleware and the browser.
export function sameOrigin(req: Request, machineBypass = false): boolean {
  const origin = req.headers.get("origin");
  const site = req.headers.get("sec-fetch-site");
  if (site !== null && site !== "same-origin") return false;
  if (origin === null) return machineBypass && site === null;
  return origin === new URL(req.url).origin;
}

export function safeLocalPath(raw: unknown, fallback = "/"): string {
  if (typeof raw !== "string" || raw.length > 2048 || !raw.startsWith("/") ||
      raw.startsWith("//") || /[\\\s\u0000-\u001f\u007f]/u.test(raw)) return fallback;
  try {
    const base = "https://local.invalid";
    const url = new URL(raw, base);
    if (url.origin !== base || url.pathname.startsWith("//")) return fallback;
    return url.pathname + url.search + url.hash;
  } catch { return fallback; }
}

export function noStore<T extends Response>(response: T): T {
  const transform = response.headers.get("cache-control")?.includes("no-transform");
  response.headers.set("Cache-Control", `private, no-store${transform ? ", no-transform" : ""}`);
  response.headers.set("Pragma", "no-cache");
  response.headers.set("Expires", "0");
  return response;
}

export class BodyError extends Error {
  constructor(readonly status: number = 400) { super("bad_input"); }
}

// Counts bytes even when Content-Length is absent or dishonest. No chunk is
// retained beyond the budget; the timer also bounds a stalled request stream.
async function bodyBytes(req: Request, maxBytes: number): Promise<Uint8Array> {
  const length = req.headers.get("content-length");
  if (length !== null && (!/^\d{1,10}$/.test(length) || Number(length) > maxBytes)) {
    void req.body?.cancel().catch(() => {});
    throw new BodyError(413);
  }
  if (req.headers.has("content-encoding") && req.headers.get("content-encoding") !== "identity") throw new BodyError(415);
  const reader = req.body?.getReader();
  if (!reader) throw new BodyError();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let total = 0;
  const chunks: Uint8Array[] = [];
  const expires = Date.now() + 15_000;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new BodyError(408)), 15_000);
  });
  try {
    let empty = 0;
    while (true) {
      if (Date.now() >= expires) throw new BodyError(408);
      const { value, done } = await Promise.race([reader.read(), timeout]);
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) throw new BodyError(413);
      empty = value.byteLength ? 0 : empty + 1;
      if (empty > 128) throw new BodyError();
      chunks.push(value);
    }
    if (length !== null && total !== Number(length)) throw new BodyError();
    const body = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
    return body;
  } catch (error) {
    void reader.cancel().catch(() => {});
    throw error instanceof BodyError ? error : new BodyError();
  } finally { clearTimeout(timer); }
}

export async function readJson(req: Request, maxBytes = 512 * 1024): Promise<unknown> {
  if (req.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") throw new BodyError(415);
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await bodyBytes(req, maxBytes))); }
  catch (error) { throw error instanceof BodyError ? error : new BodyError(); }
}

export async function readForm(req: Request): Promise<FormData> {
  const type = req.headers.get("content-type") ?? "";
  if (!/^(application\/x-www-form-urlencoded|multipart\/form-data)(;|$)/i.test(type)) throw new BodyError(415);
  const bytes = await bodyBytes(req, 16 * 1024);
  try { return await new Response(Uint8Array.from(bytes).buffer, { headers: { "Content-Type": type } }).formData(); }
  catch { throw new BodyError(); }
}

export function bodyFailure(error: unknown): Response {
  return noStore(Response.json({ error: "bad_input" }, { status: error instanceof BodyError ? error.status : 400 }));
}

export function privateRoute<R extends Request>(handler: (req: R) => Promise<Response>): (req: R) => Promise<Response> {
  return async (req) => {
    try { return noStore(await handler(req)); }
    catch (error) {
      if (error instanceof BodyError) return bodyFailure(error);
      console.warn("[http] request failed");
      return noStore(Response.json({ error: "request_failed" }, { status: 502 }));
    }
  };
}

export async function boundedWait<T>(value: PromiseLike<T>, milliseconds = 2000): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([Promise.resolve(value), new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error("dependency_unavailable")), milliseconds);
    })]);
  } finally { clearTimeout(timer); }
}
