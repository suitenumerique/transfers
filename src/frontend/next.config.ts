import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: process.env.NEXT_OUTPUT === "export" ? "export" : undefined,
  reactStrictMode: false,
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
