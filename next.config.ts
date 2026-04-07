import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow any local network origin in dev (e.g. LAN IP access)
  allowedDevOrigins: ["localhost", "127.0.0.1"],

  // Ensure static generation warning doesn't block build
  // The page uses "use client" so it's fine as a client component
  reactStrictMode: true,
};

export default nextConfig;
