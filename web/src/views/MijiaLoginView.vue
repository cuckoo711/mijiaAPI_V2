<script setup lang="ts">
import { Loading, Tickets, User } from "@element-plus/icons-vue";
import type { SyncProgress } from "../composables/useSyncProgress";

defineProps<{
  account: Record<string, unknown>;
  qrJob: Record<string, string> | null;
  syncing: boolean;
  syncProgress: SyncProgress | null;
}>();

const emit = defineEmits<{
  "start-qr-login": [];
  sync: [];
  "delete-credential": [];
  "dismiss-sync-progress": [];
}>();
</script>

<template>
  <section class="stack">
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
        <div class="card-title">账号状态</div>
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
            {{ account.status_text || (account.valid ? "有效" : "未登录或已过期") }}
          </el-tag>
        </div>
        <div class="status-details">
          <div v-if="account.exists && account.user_id">用户 ID: {{ account.user_id }}</div>
          <div v-if="account.expires_at">过期时间: {{ account.expires_at }}</div>
          <div v-if="account.expires_in_days">
            剩余时间: {{ account.expires_in_days }} 天 ({{ account.expires_in_hours }} 小时)
          </div>
        </div>
      </div>
    </el-card>

    <el-card shadow="hover" class="dashboard-card">
      <div class="card-header">
        <div class="card-icon icon-orange">
          <el-icon><Tickets /></el-icon>
        </div>
        <div class="card-title">米家登录</div>
      </div>
      <div class="card-content">
        <div class="login-actions">
          <el-button type="primary" size="large" @click="emit('start-qr-login')">
            {{ account.exists ? "重新扫码登录" : "开始扫码登录" }}
          </el-button>
          <el-button :loading="syncing" :disabled="syncing" size="large" @click="emit('sync')">
            {{ syncing ? "同步中..." : "同步家庭/设备/场景" }}
          </el-button>
          <el-button
            v-if="account.exists"
            type="danger"
            plain
            size="large"
            @click="emit('delete-credential')"
          >
            移除账号
          </el-button>
        </div>
        <div v-if="qrJob" class="qr-box">
          <img :src="qrJob.qr_image || qrJob.qr_url" alt="米家登录二维码" />
          <div class="qr-status">
            <el-tag
              :type="
                qrJob.status === 'success' ? 'success' : qrJob.status === 'failed' ? 'danger' : 'info'
              "
              size="large"
            >
              {{
                qrJob.status === "success"
                  ? "登录成功"
                  : qrJob.status === "failed"
                    ? "登录失败"
                    : "等待扫码"
              }}
            </el-tag>
            <div class="qr-message">{{ qrJob.message }}</div>
          </div>
        </div>
      </div>
    </el-card>

    <el-card v-if="syncProgress" shadow="hover" class="sync-progress-card">
      <template #header>
        <div class="progress-header">
          <div class="card-header" style="margin-bottom: 0">
            <div class="card-icon icon-blue">
              <el-icon><Loading /></el-icon>
            </div>
            <div class="card-title">同步进度</div>
          </div>
          <div style="display: flex; align-items: center; gap: 12px">
            <el-tag
              :type="
                syncProgress.status === 'completed'
                  ? 'success'
                  : syncProgress.status === 'failed'
                    ? 'danger'
                    : 'primary'
              "
              size="large"
            >
              {{
                syncProgress.status === "running"
                  ? "同步中"
                  : syncProgress.status === "completed"
                    ? "已完成"
                    : "失败"
              }}
            </el-tag>
            <el-button
              v-if="syncProgress.status !== 'running'"
              type="default"
              size="small"
              @click="emit('dismiss-sync-progress')"
            >
              关闭
            </el-button>
          </div>
        </div>
      </template>

      <div class="sync-progress-content">
        <el-progress
          :percentage="syncProgress.progress"
          :status="
            syncProgress.status === 'completed'
              ? 'success'
              : syncProgress.status === 'failed'
                ? 'exception'
                : undefined
          "
          :striped="syncProgress.status === 'running'"
          :striped-flow="syncProgress.status === 'running'"
          :stroke-width="12"
        />

        <div class="step-info">
          <el-tag type="info" size="large">{{ syncProgress.step }}</el-tag>
          <span v-if="syncProgress.current_home" class="home-info">
            家庭：{{ syncProgress.current_home }}
          </span>
        </div>

        <div class="sync-stats">
          <div class="sync-stat-item">
            <div class="sync-stat-value">
              {{ syncProgress.homes_processed }} / {{ syncProgress.homes_total }}
            </div>
            <div class="sync-stat-label">家庭</div>
          </div>
          <div class="sync-stat-item">
            <div class="sync-stat-value">{{ syncProgress.devices_found }}</div>
            <div class="sync-stat-label">设备</div>
          </div>
          <div class="sync-stat-item">
            <div class="sync-stat-value">{{ syncProgress.scenes_found }}</div>
            <div class="sync-stat-label">场景</div>
          </div>
          <div class="sync-stat-item">
            <div class="sync-stat-value">{{ syncProgress.warnings.length }}</div>
            <div class="sync-stat-label">警告</div>
          </div>
        </div>

        <div v-if="syncProgress.warnings.length > 0" class="warnings">
          <el-alert
            v-for="(warning, index) in syncProgress.warnings"
            :key="index"
            :title="`${warning.kind} - ${warning.home_name}`"
            :description="warning.message"
            type="warning"
            show-icon
            :closable="false"
          />
        </div>
      </div>
    </el-card>
  </section>
</template>
