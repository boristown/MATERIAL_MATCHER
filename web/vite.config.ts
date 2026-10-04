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
    dedupe: ['vue'],
    alias: [
      // element-ui is CJS: its require('vue') would resolve a second Vue copy
      // (vue.runtime.common.js) and every el-table body render dies across
      // instances. Pin one canonical ESM copy for everyone.
      { find: /^vue$/, replacement: fileURLToPath(new URL('./node_modules/vue/dist/vue.runtime.esm.js', import.meta.url)) },
      { find: /^element-plus$/, replacement: fileURLToPath(new URL('./src/element-plus-compat.ts', import.meta.url)) },
      { find: /^vue-router$/, replacement: fileURLToPath(new URL('./src/vue-router-compat.ts', import.meta.url)) },
    ],
  },
  server: { proxy: { '/api': 'http://127.0.0.1:18080' } },
});
