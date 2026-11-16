/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV !== "production";
const backend = process.env.ATLAS_BACKEND_URL || "http://localhost:8000";

const config = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Production: static export served by the FastAPI backend (single origin, httpOnly cookie auth).
  ...(isDev ? {} : { output: "export" }),
  images: { unoptimized: true },
  ...(isDev
    ? { async rewrites() { return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }]; } }
    : {}),
};
export default config;
