import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { HttpAgent } from "@ag-ui/client";
import { NextRequest } from "next/server";
import { getBackendOrigin, getGoogleAuthHeaders, isGoogleEndpoint } from "@/app/lib/proxy";

// Bridges the browser to the ADK backend's AG-UI endpoint.
// Supports direct local backend (port 8000) or Google Agent Runtime passthrough with ADC auth.
const backendOrigin = getBackendOrigin();
const targetUrl = `${backendOrigin}/api/adk`;

const runtime = new CopilotRuntime({
  agents: {
    social_poster: new HttpAgent({
      url: targetUrl,
      fetch: async (url: string, init: RequestInit) => {
        const headers = new Headers();
        // Copy headers from init, but if calling a Google endpoint, strip any incoming
        // proxy headers (Authorization, X-Serverless-Authorization, X-Forwarded-*)
        const isGoogle = isGoogleEndpoint(url);
        if (init.headers) {
          const srcHeaders = new Headers(init.headers);
          srcHeaders.forEach((value, key) => {
            const lowerKey = key.toLowerCase();
            if (
              isGoogle &&
              (lowerKey === "authorization" ||
                lowerKey === "x-serverless-authorization" ||
                lowerKey.startsWith("x-forwarded-"))
            ) {
              return;
            }
            headers.set(key, value);
          });
        }

        if (isGoogle) {
          const authHeaders = await getGoogleAuthHeaders(url);
          for (const [key, value] of Object.entries(authHeaders)) {
            headers.set(key, value);
          }
        }

        return fetch(url, {
          ...init,
          headers,
        });
      },
    }),
  },
});

export const POST = async (req: NextRequest) => {
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter: new ExperimentalEmptyAdapter(),
    endpoint: "/api/copilotkit",
  });
  return handleRequest(req);
};
