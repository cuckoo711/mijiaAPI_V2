<script setup lang="ts">
import { computed } from "vue";
import { securityRows } from "../data/apiDocs";
import { configBool } from "../utils/configHelpers";

const props = defineProps<{
  configs: Array<Record<string, unknown>>;
  proxyCidrs: string;
}>();

const emit = defineEmits<{
  "update:proxyCidrs": [value: string];
  "set-runtime-switch": [key: string, value: string | number | boolean];
  "sync-proxy-cidrs": [];
  "save-proxy-cidrs": [];
}>();

const runtimeConfig = computed(
  () => new Map(props.configs.map((item) => [String(item.key), item.value]))
);

function cfgBool(key: string, defaultValue = false): boolean {
  return configBool(runtimeConfig.value, key, defaultValue);
}
</script>

<template>
  <section class="stack">
    <el-card shadow="never">
      <template #header>系统安全说明</template>
      <el-alert type="warning" show-icon :closable="false">
        <template #title>
          管理台只负责配置和授权，不负责暴露公网。部署到公网前，请在反向代理层启用 HTTPS 和访问控制。
        </template>
      </el-alert>
    </el-card>
    <el-card shadow="never">
      <template #header>访问来源</template>
      <div class="security-switch-list">
        <div class="security-switch-row">
          <div>
            <div class="security-switch-title">允许局域网请求</div>
            <div class="security-switch-desc">
              允许 10.x、172.16-31.x、192.168.x、局域网 IPv6 等私有网段访问对外 API。
            </div>
          </div>
          <el-switch
            :model-value="cfgBool('ALLOW_LAN_ACCESS')"
            active-text="允许"
            inactive-text="关闭"
            inline-prompt
            @change="(value: string | number | boolean) => emit('set-runtime-switch', 'ALLOW_LAN_ACCESS', value)"
          />
        </div>
        <div class="security-switch-row danger">
          <div>
            <div class="security-switch-title">允许公网请求</div>
            <div class="security-switch-desc">
              允许公网客户端访问对外 API。开启前请确认 API Key 权限、HTTPS、反向代理和防火墙策略。
            </div>
          </div>
          <el-switch
            :model-value="cfgBool('ALLOW_PUBLIC_ACCESS')"
            active-text="允许"
            inactive-text="关闭"
            inline-prompt
            @change="(value: string | number | boolean) => emit('set-runtime-switch', 'ALLOW_PUBLIC_ACCESS', value)"
          />
        </div>
        <div class="security-switch-row">
          <div>
            <div class="security-switch-title">反向代理模式</div>
            <div class="security-switch-desc">
              信任来自可信代理的 X-Forwarded-For / X-Real-IP，再按真实客户端来源判断访问权限。
            </div>
          </div>
          <el-switch
            :model-value="cfgBool('TRUST_PROXY_HEADERS')"
            active-text="开启"
            inactive-text="关闭"
            inline-prompt
            @change="(value: string | number | boolean) => emit('set-runtime-switch', 'TRUST_PROXY_HEADERS', value)"
          />
        </div>
        <div class="proxy-config">
          <div>
            <div class="security-switch-title">可信代理地址</div>
            <div class="security-switch-desc">
              每行一个 IP 或 CIDR。只有这些代理传来的转发头会被采用。
            </div>
          </div>
          <el-input
            :model-value="proxyCidrs"
            type="textarea"
            :rows="4"
            placeholder="127.0.0.1/32&#10;::1/128&#10;192.168.1.10/32"
            @update:model-value="(value: string) => emit('update:proxyCidrs', value)"
          />
          <div class="proxy-config-actions">
            <el-button @click="emit('sync-proxy-cidrs')">还原</el-button>
            <el-button type="primary" @click="emit('save-proxy-cidrs')">保存可信代理</el-button>
          </div>
        </div>
      </div>
      <el-alert class="security-hint" type="info" show-icon :closable="false">
        <template #title>
          如果服务启动时仍监听 127.0.0.1，外部机器无法连进来。需要用
          MIJIA_SERVER_HOST=0.0.0.0 重启服务，或由反向代理转发到本服务。
        </template>
      </el-alert>
    </el-card>
    <el-card shadow="never">
      <template #header>API 文档</template>
      <div class="security-switch-list">
        <div class="security-switch-row">
          <div>
            <div class="security-switch-title">启用交互式文档</div>
            <div class="security-switch-desc">
              开启 Swagger UI 与 ReDoc。开启后会同步允许文档页面加载 OpenAPI JSON。
            </div>
          </div>
          <el-switch
            :model-value="cfgBool('DOCS_ENABLED')"
            active-text="开启"
            inactive-text="关闭"
            inline-prompt
            @change="(value: string | number | boolean) => emit('set-runtime-switch', 'DOCS_ENABLED', value)"
          />
        </div>
        <div class="security-switch-row">
          <div>
            <div class="security-switch-title">开放 OpenAPI JSON</div>
            <div class="security-switch-desc">
              单独开放 /api/v1/openapi.json，方便工具或 Agent 读取接口定义；不会放开业务 API 访问来源。
            </div>
          </div>
          <el-switch
            :model-value="cfgBool('OPENAPI_ENABLED')"
            active-text="开启"
            inactive-text="关闭"
            inline-prompt
            @change="(value: string | number | boolean) => emit('set-runtime-switch', 'OPENAPI_ENABLED', value)"
          />
        </div>
      </div>
    </el-card>
    <el-table :data="securityRows" border>
      <el-table-column prop="item" label="项目" width="160" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag type="success" effect="light">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="说明" />
    </el-table>
  </section>
</template>
