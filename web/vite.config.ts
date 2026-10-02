import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import legacy from '@vitejs/plugin-legacy';

export default defineConfig({
  plugins: [
    vue(),
    legacy({
      targets: ['chrome >= 49', 'firefox >= 52'],
      modernPolyfills: false,
    }),
  ],
  server: { proxy: { '/api': 'http://127.0.0.1:18080' } },
});
