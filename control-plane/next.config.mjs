/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // better-sqlite3 is a native module; mark it as a server-only external.
  serverExternalPackages: ["better-sqlite3"],
};

export default nextConfig;
