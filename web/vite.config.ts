import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import legacy from "@vitejs/plugin-legacy";
import AutoImport from "unplugin-auto-import/vite";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";

const androidLegacy = process.env.MIJIA_ANDROID_WEB_LEGACY === "1";

export default defineConfig({
  plugins: [
    vue(),
    ...(androidLegacy ? [legacy({
      targets: ["Chrome >= 49"],
      modernTargets: ["Chrome >= 64"],
      modernPolyfills: true,
    })] : []),
    AutoImport({
      resolvers: [ElementPlusResolver()]
    }),
    Components({
      resolvers: [ElementPlusResolver()]
    })
  ],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8123",
      "/healthz": "http://127.0.0.1:8123"
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return;
          }
          if (id.includes("@element-plus/icons-vue")) {
            return "element-plus-icons";
          }
          if (id.includes("element-plus")) {
            return "element-plus";
          }
          if (id.includes("vue-router")) {
            return "vue-router";
          }
          if (
            id.includes("/vue/") ||
            id.includes("\\vue\\") ||
            id.includes("/@vue/") ||
            id.includes("\\@vue\\")
          ) {
            return "vue";
          }
        }
      }
    }
  }
});
