/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',

  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "*.ngrok-free.dev",
      },
      {
        protocol: "https",
        hostname: "*.ngrok-free.app",
      },
      {
        protocol: "https",
        hostname: "*.ngrok.io",
      },
    ],
  },

  experimental: {
    serverActions: {
      bodySizeLimit: "20mb",
    },
  },

  // /api/* は app/api/[[...path]]/route.ts が FastAPI にプロキシ（ngrok 単一トンネル向け）
};

export default nextConfig;
