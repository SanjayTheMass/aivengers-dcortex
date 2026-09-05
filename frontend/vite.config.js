import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://13.217.203.43",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
        configure: (proxy) => {
          // A network middlebox rejects browser-identified requests to the bare
          // EC2 IP (Chrome UA + Sec-Fetch headers => empty 400). Strip them.
          proxy.on("proxyReq", (proxyReq) => {
            ["user-agent", "sec-fetch-mode", "sec-fetch-site", "sec-fetch-dest",
             "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform", "origin", "referer"]
              .forEach((header) => proxyReq.removeHeader(header));
          });
        },
      },
    },
  },
})
