import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',       // Static export for Tauri bundling
  trailingSlash: true,
  webpack(config) {
    // Allow importing shared/world.json from outside the Next.js project root
    config.resolve.alias['@shared'] = path.resolve(__dirname, '../shared')
    return config
  },
}

export default nextConfig
