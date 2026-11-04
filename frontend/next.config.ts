import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: [
    "172.22.29.152",
    "localhost",
    "127.0.0.1",
  ],
  experimental: {
    agentUpgrade: "security",
  },
};

export default nextConfig;
