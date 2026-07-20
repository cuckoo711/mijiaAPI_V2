<script setup lang="ts">
import { curlApiKey } from "../apiExamples";
import { apiEndpointRows } from "../data/apiDocs";
import type { ApiEndpointRow } from "../types/admin";

const props = defineProps<{
  apiBaseUrl: string;
  oneTimeApiKey: string;
}>();

function methodTag(method: string): "success" | "warning" | "info" {
  return method === "POST" ? "warning" : method === "GET" ? "success" : "info";
}

function endpointCurl(row: ApiEndpointRow): string {
  const lines = [
    `curl -X ${row.method} \\`,
    `  -H "Authorization: Bearer ${curlApiKey(props.oneTimeApiKey)}" \\`,
  ];
  if (row.body) {
    lines.push(`  -H "Content-Type: application/json" \\`);
    lines.push(`  -d '${row.body.replace(/\n/g, "")}' \\`);
  }
  lines.push(`  ${props.apiBaseUrl}${row.path}`);
  return lines.join("\n");
}
</script>

<template>
  <section class="stack">
    <el-card shadow="never">
      <template #header>调用方式</template>
      <div class="usage-note">
        外部调用时，把 API Key 放到 HTTP Header：<code>Authorization: Bearer YOUR_API_KEY</code>
      </div>
      <div class="doc-link-row">
        <el-button tag="a" href="/docs" target="_blank">Swagger 文档</el-button>
        <el-button tag="a" href="/redoc" target="_blank">ReDoc 文档</el-button>
        <el-button tag="a" href="/api/v1/openapi.json" target="_blank">OpenAPI JSON</el-button>
      </div>
      <pre class="usage-code"><code>curl -H "Authorization: Bearer YOUR_API_KEY" \
  {{ apiBaseUrl }}/api/v1/devices</code></pre>
      <pre class="usage-code"><code>fetch("{{ apiBaseUrl }}/api/v1/devices", {
  headers: {
    Authorization: "Bearer YOUR_API_KEY"
  }
})</code></pre>
      <el-alert type="info" show-icon :closable="false">
        <template #title>
          API Key 创建后只显示一次。Swagger/ReDoc 和 OpenAPI JSON 可在“系统安全”中开启，切换后立即生效。
        </template>
      </el-alert>
    </el-card>
    <el-card shadow="never">
      <template #header>接口文档</template>
      <el-table :data="apiEndpointRows" border>
        <el-table-column type="expand" width="48">
          <template #default="{ row }">
            <div class="endpoint-detail">
              <el-descriptions :column="1" border>
                <el-descriptions-item label="请求数据">{{ row.request }}</el-descriptions-item>
                <el-descriptions-item label="返回数据">{{ row.response }}</el-descriptions-item>
                <el-descriptions-item label="注意事项">{{ row.note }}</el-descriptions-item>
              </el-descriptions>
              <pre v-if="row.body" class="usage-code endpoint-body"><code>{{ row.body }}</code></pre>
              <pre class="usage-code endpoint-curl"><code>{{ endpointCurl(row) }}</code></pre>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="方法" width="92" align="center">
          <template #default="{ row }">
            <el-tag :type="methodTag(row.method)" effect="light">{{ row.method }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="路径" min-width="280">
          <template #default="{ row }">
            <code class="endpoint-path">{{ row.path }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="purpose" label="用途" min-width="180" />
        <el-table-column prop="permission" label="所需权限" min-width="160" />
        <el-table-column prop="request" label="请求数据" min-width="180" />
      </el-table>
    </el-card>
    <el-card shadow="never">
      <template #header>访问策略</template>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="本机调用">
          服务监听 127.0.0.1 时，只能从同一台机器访问，适合脚本或反向代理转发。
        </el-descriptions-item>
        <el-descriptions-item label="局域网调用">
          在系统安全里开启“允许局域网请求”，再让服务监听可被局域网访问的地址。
        </el-descriptions-item>
        <el-descriptions-item label="公网调用">
          在系统安全里开启“允许公网请求”，并建议只通过 HTTPS 反向代理暴露。
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
  </section>
</template>
