import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue2';
import legacy from '@vitejs/plugin-legacy';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  plugins: [
    vue(),
    legacy({
      targets: ['chrome >= 49', 'firefox >= 52'],
      modernPolyfills: false,
    }),
  ],
  resolve: {
    extensions: ['.mjs', '.mts', '.ts', '.jsx', '.tsx', '.js', '.json'],
    alias: [
      { find: /^element-plus$/, replacement: fileURLToPath(new URL('./src/element-plus-compat.ts', import.meta.url)) },
      { find: /^vue-router$/, replacement: fileURLToPath(new URL('./src/vue-router-compat.ts', import.meta.url)) },
    ],
  },
  server: { proxy: { '/api': 'http://127.0.0.1:18080' } },
});
