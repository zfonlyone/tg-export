<template>
  <div class="fade-in">
    <div class="page-header">
      <div class="header-text">
        <h1>📋 导出任务管理</h1>
        <p class="subtitle">实时监控与管理您的 Telegram 导出队列</p>
      </div>
      <div class="header-actions">
        <button @click="pauseAll" class="btn-premium warning sm" :disabled="runningCount === 0">⏸ 暂停所有任务</button>
        <button @click="resumeAll" class="btn-premium success sm" :disabled="pausedCount === 0">▶ 恢复所有任务</button>
        <button @click="removeCompleted" class="btn-premium danger sm" :disabled="completedCount === 0">🗑 清理完成记录</button>
      </div>
    </div>

    <div v-if="loading && tasks.length === 0" class="loading-state">
      <div class="spinner"></div>
      <p>正在加载任务列表...</p>
    </div>

    <div v-else-if="tasks.length === 0" class="empty-state">
      <div class="empty-icon">📁</div>
      <h3>暂无导出任务</h3>
      <p>快去创建一个新的导出任务吧！</p>
      <router-link to="/export" class="btn-premium purple" style="display: inline-flex; margin-top: 20px; text-decoration: none;">📥 开启导出</router-link>
    </div>

    <div v-else class="task-grid">
      <div v-for="task in tasks" :key="task.id" class="managed-card clickable" @click="goToDetail(task.id)">
        <div class="card-status-strip" :class="task.status"></div>
        <div class="card-main">
          <div class="card-head">
            <div class="head-left">
              <h3 class="task-title">{{ task.name }}</h3>
              <div class="task-meta">
                <span><i class="m-icon">📅</i> {{ formatDate(task.created_at) }}</span>
                <span><i class="m-icon">🆔</i> {{ task.id.substring(0, 8) }}</span>
              </div>
            </div>
            <div class="status-badge" :class="task.status">
              <span v-if="task.status === 'running' || task.status === 'extracting'" class="pulse-dot"></span>
              {{ getStatusText(task) }}
            </div>
          </div>

          <div class="progress-section">
            <div class="progress-header">
              <div class="p-left">
                <span class="percentage">{{ (task.progress || 0).toFixed(1) }}%</span>
                <span class="count">
                  {{ task.status === 'extracting' ? '正在扫描消息...' : `${task.downloaded_media} / ${task.total_media} 文件` }}
                </span>
              </div>
              <div class="p-right" v-if="task.status === 'running'">
                <span class="speed-label">{{ formatSpeed(task.download_speed) }}</span>
              </div>
            </div>
            <div class="main-progress-bar">
              <div class="bar-fill" :class="task.status" :style="{ width: (task.progress || 0) + '%' }"></div>
            </div>
          </div>

          <div class="footer-actions">
            <button @click.stop="goToDetail(task.id)" class="btn-premium info sm">📊 实时监控</button>
            <button v-if="['running', 'extracting'].includes(task.status)" @click.stop="pauseTask(task.id)" class="btn-premium warning sm">⏸ 暂停</button>
            <button v-if="task.status === 'paused'" @click.stop="resumeTask(task.id)" class="btn-premium success sm">▶ 恢复</button>
            
            <div class="footer-right">
              <button v-if="['completed', 'failed', 'cancelled'].includes(task.status)" @click.stop="deleteTask(task.id)" class="btn-premium danger sm">🗑 删除任务</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

const loading = ref(true)
const tasks = ref([])
const router = useRouter()
let refreshTimer = null

function getAuthHeader() {
  return { Authorization: `Bearer ${localStorage.getItem('token')}` }
}

async function fetchTasks() {
  try {
    const res = await axios.get('/api/export/tasks', { headers: getAuthHeader() })
    tasks.value = res.data.reverse()
  } catch (err) {
    console.error('获取任务失败:', err)
  } finally {
    loading.value = false
  }
}

async function pauseTask(id) { await axios.post(`/api/export/${id}/pause`, {}, { headers: getAuthHeader() }); fetchTasks() }
async function resumeTask(id) { await axios.post(`/api/export/${id}/resume`, {}, { headers: getAuthHeader() }); fetchTasks() }
async function deleteTask(id) { if(confirm('确定删除该记录？')) { await axios.delete(`/api/export/${id}`, { headers: getAuthHeader() }); tasks.value = tasks.value.filter(t => t.id !== id) } }

async function pauseAll() { tasks.value.filter(t => ['running', 'extracting'].includes(t.status)).forEach(t => pauseTask(t.id)) }
async function resumeAll() { tasks.value.filter(t => t.status === 'paused').forEach(t => resumeTask(t.id)) }
async function removeCompleted() { if(confirm('清空已完成的历史记录？')) { tasks.value.filter(t => t.status === 'completed').forEach(t => deleteTask(t.id)) } }

function goToDetail(id) {
  router.push(`/tasks/${id}`)
}

const runningCount = computed(() => tasks.value.filter(t => ['running', 'extracting'].includes(t.status)).length)
const pausedCount = computed(() => tasks.value.filter(t => t.status === 'paused').length)
const completedCount = computed(() => tasks.value.filter(t => t.status === 'completed').length)

function isRunning(task) { return ['running', 'extracting'].includes(task.status) }

function getStatusText(task) {
  const texts = {
    pending: '等待中',
    extracting: '正在扫描',
    running: '正在下载',
    paused: '已暂停',
    completed: '已完成',
    failed: '已失败',
    cancelled: '已取消'
  }
  return texts[task.status] || task.status
}

function getFileStatusText(status) {
  const texts = {
    waiting: '等待',
    downloading: '下载中',
    completed: '完成',
    failed: '失败',
    paused: '暂停',
    skipped: '跳过'
  }
  return texts[status] || status
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN')
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++ }
  return bytes.toFixed(1) + ' ' + units[i]
}

function formatSpeed(bytesPerSecond) {
  if (!bytesPerSecond || bytesPerSecond < 0) return '0 B/s'
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
  let i = 0
  while (bytesPerSecond >= 1024 && i < units.length - 1) { bytesPerSecond /= 1024; i++ }
  return bytesPerSecond.toFixed(1) + ' ' + units[i]
}

onMounted(() => {
  fetchTasks()
  refreshTimer = setInterval(() => {
    if (tasks.value.some(t => isRunning(t) || t.status === 'paused')) fetchTasks()
  }, 3000)
})

onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 40px;
}

.header-text h1 {
  font-size: 2rem;
  font-weight: 800;
  margin-bottom: 4px;
}

.subtitle { color: #71717a; }

.task-grid { display: grid; gap: 24px; }

.managed-card {
  background: white;
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid #f4f4f5;
  box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05);
  display: flex;
  transition: transform 0.2s;
}

.managed-card:hover { transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1); }

.card-status-strip { width: 6px; }
.card-status-strip.running, .card-status-strip.extracting { background: #3b82f6; }
.card-status-strip.completed { background: #22c55e; }
.card-status-strip.paused { background: #f59e0b; }
.card-status-strip.failed { background: #ef4444; }

.card-main { flex: 1; padding: 24px; }

.card-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }

.task-title { font-size: 1.25rem; font-weight: 700; color: #18181b; margin-bottom: 6px; }
.task-meta { display: flex; gap: 16px; font-size: 0.85rem; color: #71717a; }
.m-icon { margin-right: 4px; font-style: normal; }

.status-badge {
  padding: 6px 12px;
  border-radius: 50px;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-badge.running, .status-badge.extracting { background: #dbeafe; color: #1e40af; }
.status-badge.completed { background: #dcfce7; color: #166534; }
.status-badge.paused { background: #fef3c7; color: #92400e; }
.status-badge.failed { background: #fee2e2; color: #991b1b; }

.pulse-dot {
  width: 8px;
  height: 8px;
  background: currentColor;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(1.2); }
  100% { opacity: 1; transform: scale(1); }
}

/* Progress Sections */
.progress-section { margin-bottom: 24px; }
.progress-header { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 8px; }
.percentage { font-size: 1.5rem; font-weight: 800; color: #18181b; line-height: 1; }
.count { font-size: 0.85rem; color: #71717a; margin-left: 8px; }
.p-right { text-align: right; }
.speed-label { display: block; font-weight: 700; color: #3b82f6; font-size: 0.9rem; }
.etr { font-size: 0.75rem; color: #71717a; }

.main-progress-bar { height: 10px; background: #f4f4f5; border-radius: 5px; overflow: hidden; }
.bar-fill { height: 100%; transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1); background: #3b82f6; }
.bar-fill.completed { background: #22c55e; }
.bar-fill.paused { background: #f59e0b; }
.bar-fill.failed { background: #ef4444; }

.btn-mini-retry { background: none; border: none; cursor: pointer; opacity: 0.6; transition: 0.2s; font-size: 1rem; }
.btn-mini-retry:hover { opacity: 1; transform: scale(1.1); }

/* Footer Actions */
.footer-actions { display: flex; gap: 10px; align-items: center; }

.footer-right { margin-left: auto; display: flex; gap: 10px; }

.loading-state, .empty-state { text-align: center; padding: 100px 20px; color: #71717a; }
.spinner { width: 48px; height: 48px; border: 4px solid #f4f4f5; border-top-color: #3b82f6; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px; }
@keyframes spin { to { transform: rotate(360deg); } }
.empty-icon { font-size: 4rem; margin-bottom: 20px; }

.animate-slide {
  animation: slideDown 0.3s ease-out;
}
@keyframes slideDown {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
