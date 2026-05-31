import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  output: 'standalone',
  experimental: {
    middlewareClientMaxBodySize: '200mb',
  },
  async rewrites() {
    // Prod defaults to 8080 (scripts/prod.sh); dev sets DATA_AGENT_API_ORIGIN to 8081 at startup.
    const backend = process.env.DATA_AGENT_API_ORIGIN || 'http://127.0.0.1:8080'
    return [
      {
        source: '/api/:path*',
        destination: `${backend}/api/:path*`,
      },
    ]
  },
}

export default nextConfig
