export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function detail(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg: unknown }).msg) : String(x))).join("; ");
  }
  return "request failed";
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "x-atlas-client": "web", ...(init.headers as Record<string, string>) };
  let body = init.body;
  if (init.json !== undefined) { headers["content-type"] = "application/json"; body = JSON.stringify(init.json); }
  const res = await fetch(path, { ...init, body, headers, credentials: "same-origin", cache: "no-store" });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/")) {
    window.location.href = "/login";
    throw new ApiError(401, "authentication required");
  }
  const ctype = res.headers.get("content-type") || "";
  const data = ctype.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError(res.status, detail(data));
  return data as T;
}

export const post = <T = unknown>(path: string, json?: unknown) => api<T>(path, { method: "POST", json: json ?? {} });
export const put = <T = unknown>(path: string, json: unknown) => api<T>(path, { method: "PUT", json });
