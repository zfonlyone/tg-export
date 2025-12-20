<template>
  <div class="fade-in">
    <h1 style="margin-bottom: 20px;">📊 仪表盘</h1>
    
    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="icon">📋</div>
        <div class="value">{{ stats.totalTasks }}</div>
        <div class="label">总任务数</div>
      </div>
      <div class="stat-card">
        <div class="icon">✅</div>
        <div class="value">{{ stats.completedTasks }}</div>
        <div class="label">已完成</div>
      </div>
      <div class="stat-card">
        <div class="icon">🔄</div>
        <div class="value">{{ stats.runningTasks }}</div>
        <div class="label">进行中</div>
      </div>
      <div class="stat-card">
        <div class="icon">💾</div>
        <div class="value">{{ formatSize(stats.totalSize) }}</div>
        <div class="label">导出大小</div>
      </div>
    </div>
    
    <!-- Telegram 状态 -->
    <div class="card">
      <div class="card-header">
        <h2>🔗 Telegram 连接状态</h2>
        <button @click="refreshStatus" class="btn btn-outline">刷新</button>
      </div>
      
      <div v-if="loading" class="loading">
        <div class="spinner"></div>
      </div>
      
      <div v-else-if="telegramStatus.authorized">
        <div style="display: flex; align-items: center; gap: 15px;">
          <div style="width: 50px; height: 50px; background: var(--primary); border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-size: 24px;">
            {{ telegramStatus.user?.first_name?.[0] || '?' }}
          </div>
          <div>
            <div style="font-weight: 600;">{{ telegramStatus.user?.first_name }} {{ telegramStatus.user?.last_name }}</div>
            <div style="color: #666;">@{{ telegramStatus.user?.username || 'N/A' }}</div>
          </div>
          <span class="status-badge status-completed" style="margin-left: auto;">已连接</span>
        </div>
      </div>
      
      <div v-else>
        <p style="color: #666; margin-bottom: 15px;">请先登录 Telegram 以使用导出功能</p>
        <router-link to="/settings" class="btn btn-primary">前往设置</router-link>
      </div>
    </div>
    
    <!-- 最近任务 -->
    <div class="card">
      <div class="card-header">
        <h2>📋 最近任务</h2>
        <router-link to="/tasks" class="btn btn-outline">查看全部</router-link>
      </div>
      
      <div v-if="recentTasks.length === 0" style="text-align: center; padding: 30px; color: #666;">
        暂无导出任务
      </div>
      
      <table v-else class="table">
        <thead>
          <tr>
            <th>任务名称</th>
            <th>状态</th>
            <th>进度</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in recentTasks" :key="task.id">
            <td>{{ task.name }}</td>
            <td>
              <span :class="'status-badge status-' + task.status">
                {{ statusText[task.status] }}
              </span>
            </td>
            <td>
              <div class="progress" style="width: 100px;">
                <div class="progress-bar" :style="{ width: task.progress + '%' }"></div>
              </div>
            </td>
            <td>{{ formatDate(task.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    
    <!-- 快速操作 -->
    <div class="card">
      <div class="card-header">
        <h2>⚡ 快速操作</h2>
      </div>
      <div style="display: flex; gap: 15px; flex-wrap: wrap;">
        <router-link to="/export" class="btn btn-primary">
          📥 新建导出
        </router-link>
        <router-link to="/tasks" class="btn btn-outline">
          📋 查看任务
        </router-link>
        <a href="/exports" target="_blank" class="btn btn-outline">
          📁 浏览文件
        </a>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const loading = ref(true)
const telegramStatus = ref({ authorized: false, user: null })
const recentTasks = ref([])
const stats = ref({
  totalTasks: 0,
  completedTasks: 0,
  runningTasks: 0,
  totalSize: 0
})

const statusText = {
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消'
}

function getAuthHeader() {
  return { Authorization: `Bearer ${localStorage.getItem('token')}` }
}

async function refreshStatus() {
  loading.value = true
  try {
    const [statusRes, tasksRes] = await Promise.all([
      axios.get('/api/telegram/status', { headers: getAuthHeader() }),
      axios.get('/api/export/tasks', { headers: getAuthHeader() })
    ])
    
    telegramStatus.value = statusRes.data
    recentTasks.value = tasksRes.data.slice(-5).reverse()
    
    // 计算统计
    const tasks = tasksRes.data
    stats.value = {
      totalTasks: tasks.length,
      completedTasks: tasks.filter(t => t.status === 'completed').length,
      runningTasks: tasks.filter(t => t.status === 'running').length,
      totalSize: tasks.reduce((sum, t) => sum + (t.downloaded_size || 0), 0)
    }
  } catch (err) {
    console.error('获取状态失败:', err)
  } finally {
    loading.value = false
  }
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024
    i++
  }
  return bytes.toFixed(1) + ' ' + units[i]
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN')
}

onMounted(refreshStatus)
</script>
