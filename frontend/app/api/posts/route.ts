import { NextRequest } from "next/server";
import { proxyToBackend } from "@/app/lib/proxy";

export async function GET(req: NextRequest) {
  return proxyToBackend(req, "/api/posts");
}
