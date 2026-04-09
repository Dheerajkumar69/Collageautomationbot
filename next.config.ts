import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a static site to `out/` for Netlify static hosting.
  output: "export",

  // Ensure static generation warning doesn't block build
  // The page uses "use client" so it's fine as a client component
  reactStrictMode: true,
};

export default nextConfig;
