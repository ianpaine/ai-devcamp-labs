import { NextRequest } from "next/server";
import { proxyToBackend } from "@/app/lib/proxy";

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const { path } = await context.params;
  const subPath = Array.isArray(path) ? path.join("/") : (path || "");
  return proxyToBackend(req, `/outputs/${subPath}`);
}
