import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow long-running API calls (dispatch pipeline runs multiple LLM agents)
  httpAgentOptions: {
    keepAlive: true,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
  experimental: {
    proxyTimeout: 300_000, // 5 minutes for multi-agent dispatch pipeline
  },
};

export default nextConfig;
