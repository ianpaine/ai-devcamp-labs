import { GoogleAuth } from "google-auth-library";
import { NextRequest } from "next/server";

const auth = new GoogleAuth({
  scopes: "https://www.googleapis.com/auth/cloud-platform",
});

/**
 * Returns the backend origin to proxy requests to.
 * Supports ADK_BACKEND_ORIGIN, and falls back to ADK_BACKEND_URL origin or localhost:8000.
 */
export function getBackendOrigin(): string {
  if (process.env.ADK_BACKEND_ORIGIN) {
    return process.env.ADK_BACKEND_ORIGIN.replace(/\/+$/, "");
  }
  if (process.env.ADK_BACKEND_URL) {
    try {
      const url = new URL(process.env.ADK_BACKEND_URL);
      // Strip trailing /api/adk if someone provided the full endpoint
      return `${url.protocol}//${url.host}${url.pathname.replace(/\/api\/adk\/?$/, "")}`.replace(/\/+$/, "");
    } catch {
      // ignore invalid URL
    }
  }
  return "http://localhost:8000";
}

/**
 * Checks if the target URL points to a Google endpoint (e.g. *.googleapis.com or *.google.com).
 */
export function isGoogleEndpoint(urlString: string): boolean {
  try {
    const url = new URL(urlString);
    const hostname = url.hostname.toLowerCase();
    return hostname.endsWith(".googleapis.com") || hostname.endsWith(".google.com");
  } catch {
    return false;
  }
}

/**
 * Retrieves authentication request headers from GoogleAuth if targeting a Google endpoint.
 * This includes Authorization and x-goog-user-project (quota project).
 */
export async function getGoogleAuthHeaders(targetUrl: string): Promise<Record<string, string>> {
  if (!isGoogleEndpoint(targetUrl)) {
    return {};
  }
  try {
    const result: Record<string, string> = {};
    const token = await auth.getAccessToken();
    if (token) {
      result["Authorization"] = `Bearer ${token}`;
    } else {
      const client = await auth.getClient();
      const headers = await client.getRequestHeaders(targetUrl);
      if (headers instanceof Headers) {
        headers.forEach((v, k) => {
          result[k] = v;
        });
      } else if (headers && typeof headers === "object") {
        Object.entries(headers).forEach(([k, v]) => {
          if (typeof v === "string") {
            result[k] = v;
          }
        });
      }
    }

    try {
      const projectId = await auth.getProjectId();
      if (projectId && !result["x-goog-user-project"]) {
        result["x-goog-user-project"] = projectId;
      }
    } catch {
      // ignore
    }

    return result;
  } catch (err) {
    console.error("Failed to acquire Google auth headers:", err);
    return {};
  }
}

/**
 * Proxies an incoming NextRequest to the backend service.
 * Automatically attaches Google ADC auth headers if the target is a Google endpoint.
 * Passes the upstream response body straight through as a stream to preserve SSE.
 */
export async function proxyToBackend(
  req: NextRequest,
  targetPath: string
): Promise<Response> {
  const backendOrigin = getBackendOrigin();
  const search = req.nextUrl.search || "";
  const targetUrl = `${backendOrigin}${targetPath}${search}`;

  const headers = new Headers();
  // Copy request headers except host/connection
  const isGoogle = isGoogleEndpoint(targetUrl);
  req.headers.forEach((value, key) => {
    const lowerKey = key.toLowerCase();
    if (lowerKey !== "host" && lowerKey !== "connection" && lowerKey !== "content-length") {
      // If we are calling a Google endpoint, strip any incoming client auth headers
      // (such as Authorization or X-Serverless-Authorization injected by cloud-run-proxy)
      // because Google API Gateway / Vertex AI Reasoning Engine rejects foreign or conflicting auth headers!
      if (
        isGoogle &&
        (lowerKey === "authorization" ||
          lowerKey === "x-serverless-authorization" ||
          lowerKey.startsWith("x-forwarded-"))
      ) {
        return;
      }
      headers.set(key, value);
    }
  });

  // Attach Google ADC headers (Authorization + x-goog-user-project) only if target is a Google endpoint
  if (isGoogle) {
    const authHeaders = await getGoogleAuthHeaders(targetUrl);
    for (const [key, value] of Object.entries(authHeaders)) {
      headers.set(key, value);
    }
  }

  // Determine request body and duplex mode
  const init: RequestInit & { duplex?: "half" } = {
    method: req.method,
    headers,
    cache: "no-store",
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = req.body;
    init.duplex = "half";
  }

  const upstreamRes = await fetch(targetUrl, init);

  const responseHeaders = new Headers();
  upstreamRes.headers.forEach((value, key) => {
    // Preserve content-type, cache-control, etc., while avoiding hop-by-hop and encoding headers
    // Note: fetch() decompresses gzip responses, so content-encoding / content-length must not be forwarded
    const lowerKey = key.toLowerCase();
    if (
      lowerKey !== "transfer-encoding" &&
      lowerKey !== "connection" &&
      lowerKey !== "content-encoding" &&
      lowerKey !== "content-length"
    ) {
      responseHeaders.set(key, value);
    }
  });

  return new Response(upstreamRes.body, {
    status: upstreamRes.status,
    statusText: upstreamRes.statusText,
    headers: responseHeaders,
  });
}
