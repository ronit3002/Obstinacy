import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  base: './', // relative paths so the static build works on any host / sub-path
  plugins: [react(), tailwindcss()],
})
