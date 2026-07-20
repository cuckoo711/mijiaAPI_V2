<script setup lang="ts">
import { Cpu, Key, Monitor, User } from "@element-plus/icons-vue";
import type { ApiKeyItem, DeviceItem, HomeItem, SceneItem } from "../types/admin";

defineProps<{
  health: { status: string; version: string } | null;
  account: Record<string, unknown>;
  devices: DeviceItem[];
  homes: HomeItem[];
  scenes: SceneItem[];
  apiKeys: ApiKeyItem[];
}>();
</script>

<template>
  <section class="dashboard-grid">
    <el-card shadow="hover" class="dashboard-card status-card">
      <div class="card-header">
        <div class="card-icon" :class="health?.status === 'ok' ? 'icon-success' : 'icon-danger'">
          <el-icon><Monitor /></el-icon>
        </div>
        <div class="card-title">服务状态</div>
      </div>
      <div class="card-content">
        <div class="status-indicator">
          <el-tag :type="health?.status === 'ok' ? 'success' : 'danger'" size="large">
            {{ health?.status === "ok" ? "运行正常" : "异常" }}
          </el-tag>
        </div>
        <div class="status-details">
          <span>版本 {{ health?.version || "2.0.0" }}</span>
        </div>
      </div>
    </el-card>

    <el-card shadow="hover" class="dashboard-card account-card">
      <div class="card-header">
        <div
          class="card-icon"
          :class="
            account.status === 'valid'
              ? 'icon-success'
              : account.status === 'expiring_soon'
                ? 'icon-warning'
                : 'icon-danger'
          "
        >
          <el-icon><User /></el-icon>
        </div>
        <div class="card-title">米家账号</div>
      </div>
      <div class="card-content">
        <div class="status-indicator">
          <el-tag
            :type="
              account.status === 'valid'
                ? 'success'
                : account.status === 'expiring_soon'
                  ? 'warning'
                  : 'danger'
            "
            size="large"
          >
            {{ account.status_text || (account.valid ? "有效" : "未登录") }}
          </el-tag>
        </div>
        <div v-if="account.exists && account.user_id" class="status-details">
          <span>ID: {{ account.user_id }}</span>
        </div>
      </div>
    </el-card>

    <el-card shadow="hover" class="dashboard-card devices-card">
      <div class="card-header">
        <div class="card-icon icon-blue">
          <el-icon><Cpu /></el-icon>
        </div>
        <div class="card-title">设备统计</div>
      </div>
      <div class="card-content">
        <div class="stats-grid">
          <div class="stat-item">
            <div class="stat-value">{{ devices.length }}</div>
            <div class="stat-label">设备总数</div>
          </div>
          <div class="stat-item">
            <div class="stat-value">{{ homes.length }}</div>
            <div class="stat-label">家庭数量</div>
          </div>
          <div class="stat-item">
            <div class="stat-value">{{ scenes.length }}</div>
            <div class="stat-label">场景数量</div>
          </div>
        </div>
      </div>
    </el-card>

    <el-card shadow="hover" class="dashboard-card api-card">
      <div class="card-header">
        <div class="card-icon icon-purple">
          <el-icon><Key /></el-icon>
        </div>
        <div class="card-title">API Key</div>
      </div>
      <div class="card-content">
        <div class="stats-grid">
          <div class="stat-item">
            <div class="stat-value">{{ apiKeys.length }}</div>
            <div class="stat-label">密钥总数</div>
          </div>
          <div class="stat-item">
            <div class="stat-value">{{ apiKeys.filter((k) => k.is_active).length }}</div>
            <div class="stat-label">启用中</div>
          </div>
          <div class="stat-item">
            <div class="stat-value">{{ apiKeys.reduce((sum, k) => sum + k.use_count, 0) }}</div>
            <div class="stat-label">总调用次数</div>
          </div>
        </div>
      </div>
    </el-card>
  </section>
</template>
