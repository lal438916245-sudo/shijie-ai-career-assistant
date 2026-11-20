import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { fileURLToPath, URL } from "node:url"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy: {
    "/api/practice": { target: "http://127.0.0.1:8765", changeOrigin: true },
    "/api/sdk": { target: "http://127.0.0.1:8767", changeOrigin: true,
      configure: (proxy) => { proxy.on("proxyReq", (proxyReq) => {
        // Never trust a browser-supplied service capability, and never expose it in the client bundle.
        proxyReq.removeHeader("X-CP-Local-Key")
        const key = process.env.CP_WORKFLOW_PREVIEW_KEY
        if (key && /^[0-9a-f]{64}$/.test(key)) proxyReq.setHeader("X-CP-Local-Key", key)
      }) }
    },
    "/api/live": { target: "http://127.0.0.1:8766", changeOrigin: true,
      configure: (proxy) => { proxy.on("proxyReq", (proxyReq) => {
        // Never trust a browser-supplied service capability, and never expose it in the client bundle.
        proxyReq.removeHeader("X-CP-Local-Key")
        const key = process.env.CP_WORKFLOW_PREVIEW_KEY
        if (key && /^[0-9a-f]{64}$/.test(key)) proxyReq.setHeader("X-CP-Local-Key", key)
      }) }
    }
  } },
  preview: { host: "127.0.0.1", port: 5173, strictPort: true, proxy: {
    "/api/practice": { target: "http://127.0.0.1:8765", changeOrigin: true },
    "/api/sdk": { target: "http://127.0.0.1:8767", changeOrigin: true,
      configure: (proxy) => { proxy.on("proxyReq", (proxyReq) => {
        // Never trust a browser-supplied service capability, and never expose it in the client bundle.
        proxyReq.removeHeader("X-CP-Local-Key")
        const key = process.env.CP_WORKFLOW_PREVIEW_KEY
        if (key && /^[0-9a-f]{64}$/.test(key)) proxyReq.setHeader("X-CP-Local-Key", key)
      }) }
    },
    "/api/live": { target: "http://127.0.0.1:8766", changeOrigin: true,
      configure: (proxy) => { proxy.on("proxyReq", (proxyReq) => {
        // Never trust a browser-supplied service capability, and never expose it in the client bundle.
        proxyReq.removeHeader("X-CP-Local-Key")
        const key = process.env.CP_WORKFLOW_PREVIEW_KEY
        if (key && /^[0-9a-f]{64}$/.test(key)) proxyReq.setHeader("X-CP-Local-Key", key)
      }) }
    }
  } },
})
