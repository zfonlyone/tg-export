<template>
  <div class="fade-in">
    <div class="page-header">
      <div class="header-text">
        <h1>📋 导出任务中心</h1>
        <p class="subtitle">搜索、筛选并快速处理 Telegram 导出任务</p>
      </div>
      <div class="header-actions">
        <button @click="fetchTasks" class="btn-premium info sm">🔄 刷新</button>
        <button @click="pauseAll" class="btn-premium warning sm" :disabled="runningCount === 0">⏸ 暂停全部运行中</button>
        <button @click="resumeAll" class="btn-premium success sm" :disabled="pausedCount === 0">▶ 恢复全部暂停</button>
        <button @click="removeCompleted" class="btn-premium danger sm" :disabled="completedCount === 0">🗑 清理完成记录</button>
      </div>
    </div>

    <div class="stats-grid" v-if="tasks.length">
      <div class="stat-card">
        <div class="stat-label">总任务</div>
        <div class="stat-value">{{ tasks.length }}</div>
      </div>
      <div class="stat-card success">
        <div class="stat-label">已完成</div>
        <div class="stat-value">{{ completedCount }}</div>
      </div>
      <div class="stat-card info">
        <div class="stat-label">进行中</div>
        <div class="stat-value">{{ runningCount }}</div>
      </div>
      <div class="stat-card danger">
        <div class="stat-label">失败</div>
        <div class="stat-value">{{ failedCount }}</div>
      </div>
    </div>

    <div class="filter-panel" v-if="tasks.length">
      <div class="filter-top-row">
        <div class="search-box">
          <span class="search-icon">🔎</span>
          <input
            v-model.trim="searchQuery"
            class="search-input"
            placeholder="搜索任务名 / 聊天 ID / 消息范围 / 错误信息"
          >
        </div>

        <label class="toggle-chip">
          <input type="checkbox" v-model="showOnlyFailedWithReason">
          <span>仅看带失败原因</span>
        </label>
      </div>

      <div class="filter-groups">
        <div class="filter-group">
          <span class="group-label">状态</span>
          <div class="chips">
            <button
              v-for="option in statusOptions"
              :key="option.value"
              class="chip-btn"
              :class="{ active: statusFilter === option.value }"
              @click="statusFilter = option.value"
            >
              {{ option.label }}
            </button>
          </div>
        </div>

        <div class="filter-group">
          <span class="group-label">任务类型</span>
          <div class="chips">
            <button class="chip-btn" :class="{ active: modeFilter === 'all' }" @click="modeFilter = 'all'">全部</button>
            <button class="chip-btn" :class="{ active: modeFilter === 'single' }" @click="modeFilter = 'single'">🎯 单文件</button>
            <button class="chip-btn" :class="{ active: modeFilter === 'batch' }" @click="modeFilter = 'batch'">📦 批量</button>
          </div>
        </div>

        <div class="filter-group">
          <span class="group-label">聊天范围</span>
          <div class="chips">
            <button class="chip-btn" :class="{ active: chatFilter === 'all' }" @click="chatFilter = 'all'">全部</button>
            <button class="chip-btn" :class="{ active: chatFilter === 'single-chat' }" @click="chatFilter = 'single-chat'">单频道</button>
            <button class="chip-btn" :class="{ active: chatFilter === 'multi-chat' }" @click="chatFilter = 'multi-chat'">多频道</button>
            <button class="chip-btn" :class="{ active: chatFilter === 'auto' }" @click="chatFilter = 'auto'">自动范围</button>
          </div>
        </div>
      </div>

      <div class="filter-summary">
        <span>当前显示 <strong>{{ filteredTasks.length }}</strong> / {{ tasks.length }} 个任务</span>
        <button v-if="hasActiveFilters" class="text-reset" @click="resetFilters">清空筛选</button>
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
      <router-link to="/export" class="btn-premium purple cta-link">📥 开启导出</router-link>
    </div>

    <div v-else-if="filteredTasks.length === 0" class="empty-state compact">
      <div class="empty-icon">🧹</div>
      <h3>没有符合筛选条件的任务</h3>
      <p>可以试试放宽搜索词或清空筛选条件。</p>
      <button class="btn-premium info sm" @click="resetFilters">清空筛选</button>
    </div>

    <div v-else class="task-grid">
      <div v-for="task in filteredTasks" :key="task.id" class="managed-card clickable" @click="goToDetail(task.id)">
        <div class="card-status-strip" :class="task.status"></div>
        <div class="card-main">
          <div class="card-head">
            <div class="head-left">
              <div class="title-row">
                <h3 class="task-title">{{ task.name }}</h3>
                <span class="type-tag" :class="getTaskMode(task)">
                  {{ getTaskMode(task) === 'single' ? '🎯 单文件' : '📦 批量' }}
                </span>
                <span class="chat-tag">{{ formatChatScope(task) }}</span>
              </div>
              <div class="task-meta">
                <span><i class="m-icon">📅</i> {{ formatDate(task.created_at) }}</span>
                <span><i class="m-icon">🆔</i> {{ task.id.substring(0, 8) }}</span>
                <span><i class="m-icon">↔️</i> {{ formatMessageRange(task) }}</span>
              </div>
            </div>
            <div class="status-badge" :class="task.status">
              <span v-if="['running', 'extracting'].includes(task.status)" class="pulse-dot"></span>
              {{ getStatusText(task) }}
            </div>
          </div>

          <div class="intent-line">
            {{ formatTaskIntent(task) }}
          </div>

          <div v-if="task.error" class="error-banner">
            <span class="error-label">失败原因</span>
            <span class="error-text">{{ task.error }}</span>
          </div>

          <div v-else-if="task.last_verify_result && task.status !== 'failed'" class="info-banner">
            <span class="info-label">最近校验</span>
            <span class="info-text">{{ task.last_verify_result }}</span>
          </div>

          <div class="progress-section">
            <div class="progress-header">
              <div class="p-left">
                <span class="percentage">{{ (task.progress || 0).toFixed(1) }}%</span>
                <span class="count">
                  {{ task.status === 'extracting' ? '正在扫描消息...' : `${task.downloaded_media} / ${task.total_media} 文件` }}
                </span>
              </div>
              <div class="p-right">
                <span v-if="task.status === 'running'" class="speed-label">{{ formatSpeed(task.download_speed) }}</span>
                <span v-else-if="task.status === 'completed'" class="size-label">{{ formatSize(task.downloaded_size) }}</span>
              </div>
            </div>
            <div class="main-progress-bar">
              <div class="bar-fill" :class="task.status" :style="{ width: (task.progress || 0) + '%' }"></div>
            </div>
          </div>

          <div class="footer-actions">
            <button @click.stop="goToDetail(task.id)" class="btn-premium info sm">📊 查看详情</button>
            <button v-if="['running', 'extracting'].includes(task.status)" @click.stop="pauseTask(task.id)" class="btn-premium warning sm">⏸ 暂停</button>
            <button v-if="task.status === 'paused'" @click.stop="resumeTask(task.id)" class="btn-premium success sm">▶ 恢复</button>
            <button v-if="task.status === 'failed'" @click.stop="goToDetail(task.id)" class="btn-premium warning sm">🔍 去处理失败</button>
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

const searchQuery = ref('')
const statusFilter = ref('all')
const modeFilter = ref('all')
const chatFilter = ref('all')
const showOnlyFailedWithReason = ref(false)

const statusOptions = [
  { value: 'all', label: '全部' },
  { value: 'running', label: '运行中' },
  { value: 'extracting', label: '扫描中' },
  { value: 'paused', label: '已暂停' },
  { value: 'failed', label: '失败' },
  { value: 'completed', label: '已完成' },
  { value: 'cancelled', label: '已取消' }
]

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

async function pauseTask(id) {
  await axios.post(`/api/export/${id}/pause`, {}, { headers: getAuthHeader() })
  fetchTasks()
}

async function resumeTask(id) {
  await axios.post(`/api/export/${id}/resume`, {}, { headers: getAuthHeader() })
  fetchTasks()
}

async function deleteTask(id) {
  if (confirm('确定删除该记录？')) {
    await axios.delete(`/api/export/${id}`, { headers: getAuthHeader() })
    tasks.value = tasks.value.filter(t => t.id !== id)
  }
}

async function pauseAll() {
  await Promise.all(tasks.value.filter(t => ['running', 'extracting'].includes(t.status)).map(t => pauseTask(t.id)))
}

async function resumeAll() {
  await Promise.all(tasks.value.filter(t => t.status === 'paused').map(t => resumeTask(t.id)))
}

async function removeCompleted() {
  if (confirm('清空已完成的历史记录？')) {
    await Promise.all(tasks.value.filter(t => t.status === 'completed').map(t => deleteTask(t.id)))
  }
}

function goToDetail(id) {
  router.push(`/tasks/${id}`)
}

const runningCount = computed(() => tasks.value.filter(t => ['running', 'extracting'].includes(t.status)).length)
const pausedCount = computed(() => tasks.value.filter(t => t.status === 'paused').length)
const completedCount = computed(() => tasks.value.filter(t => t.status === 'completed').length)
const failedCount = computed(() => tasks.value.filter(t => t.status === 'failed').length)

const hasActiveFilters = computed(() => {
  return Boolean(
    searchQuery.value ||
    statusFilter.value !== 'all' ||
    modeFilter.value !== 'all' ||
    chatFilter.value !== 'all' ||
    showOnlyFailedWithReason.value
  )
})

const filteredTasks = computed(() => {
  return tasks.value.filter(task => {
    if (statusFilter.value !== 'all' && task.status !== statusFilter.value) {
      return false
    }

    const mode = getTaskMode(task)
    if (modeFilter.value !== 'all' && mode !== modeFilter.value) {
      return false
    }

    const scope = getChatScopeType(task)
    if (chatFilter.value !== 'all' && scope !== chatFilter.value) {
      return false
    }

    if (showOnlyFailedWithReason.value && !(task.status === 'failed' && task.error)) {
      return false
    }

    if (searchQuery.value) {
      const q = searchQuery.value.toLowerCase()
      const haystacks = [
        task.name,
        task.id,
        task.error,
        task.last_verify_result,
        formatChatScope(task),
        formatMessageRange(task),
        formatTaskIntent(task),
        ...(task.options?.specific_chats || []).map(String)
      ].filter(Boolean).join(' ').toLowerCase()

      if (!haystacks.includes(q)) {
        return false
      }
    }

    return true
  })
})

function isRunning(task) {
  return ['running', 'extracting'].includes(task.status)
}

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

function formatDate(dateStr) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN')
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024
    i++
  }
  return bytes.toFixed(1) + ' ' + units[i]
}

function formatSpeed(bytesPerSecond) {
  if (!bytesPerSecond || bytesPerSecond < 0) return '0 B/s'
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
  let i = 0
  while (bytesPerSecond >= 1024 && i < units.length - 1) {
    bytesPerSecond /= 1024
    i++
  }
  return bytesPerSecond.toFixed(1) + ' ' + units[i]
}

function getTaskMode(task) {
  const opts = task.options || {}
  return opts.message_to > 0 && opts.message_from === opts.message_to ? 'single' : 'batch'
}

function getChatScopeType(task) {
  const chats = task.options?.specific_chats || []
  if (!chats.length) return 'auto'
  if (chats.length === 1) return 'single-chat'
  return 'multi-chat'
}

function formatChatScope(task) {
  const chats = task.options?.specific_chats || []
  if (!chats.length) return '自动范围'
  if (chats.length === 1) return `频道 ${chats[0]}`
  return `${chats.length} 个频道`
}

function formatMessageRange(task) {
  const opts = task.options || {}
  if (opts.message_to > 0) return `${opts.message_from} - ${opts.message_to}`
  return `${opts.message_from || 1} - 最新`
}

function formatTaskIntent(task) {
  const modeText = getTaskMode(task) === 'single' ? '单消息/单文件导出' : '批量导出'
  return `${modeText} · ${formatChatScope(task)} · 消息范围 ${formatMessageRange(task)}`
}

function resetFilters() {
  searchQuery.value = ''
  statusFilter.value = 'all'
  modeFilter.value = 'all'
  chatFilter.value = 'all'
  showOnlyFailedWithReason.value = false
}

onMounted(() => {
  fetchTasks()
  refreshTimer = setInterval(() => {
    if (tasks.value.some(t => isRunning(t) || t.status === 'paused')) fetchTasks()
  }, 3000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 28px;
}

.header-text h1 {
  font-size: 2rem;
  font-weight: 800;
  margin-bottom: 4px;
}

.subtitle {
  color: #71717a;
}

.header-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 18px;
}

.stat-card {
  background: white;
  border: 1px solid #f1f5f9;
  border-radius: 18px;
  padding: 18px 20px;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.04);
}

.stat-card.success { background: linear-gradient(180deg, #f0fdf4, #ffffff); }
.stat-card.info { background: linear-gradient(180deg, #eff6ff, #ffffff); }
.stat-card.danger { background: linear-gradient(180deg, #fef2f2, #ffffff); }

.stat-label {
  color: #64748b;
  font-size: 0.9rem;
  margin-bottom: 6px;
}

.stat-value {
  font-size: 2rem;
  font-weight: 800;
  color: #0f172a;
}

.filter-panel {
  background: white;
  border: 1px solid #eef2f7;
  border-radius: 20px;
  padding: 18px;
  margin-bottom: 20px;
  box-shadow: 0 4px 18px rgba(15, 23, 42, 0.04);
}

.filter-top-row {
  display: flex;
  gap: 12px;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.search-box {
  position: relative;
  flex: 1;
  min-width: 260px;
}

.search-icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  opacity: 0.6;
}

.search-input {
  width: 100%;
  height: 46px;
  border-radius: 14px;
  border: 1px solid #dbe3ee;
  background: #f8fafc;
  padding: 0 16px 0 42px;
  font-size: 0.95rem;
  outline: none;
}

.search-input:focus {
  border-color: #60a5fa;
  background: white;
  box-shadow: 0 0 0 4px rgba(96, 165, 250, 0.12);
}

.toggle-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 999px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #334155;
  font-size: 0.9rem;
}

.filter-groups {
  display: grid;
  gap: 14px;
}

.filter-group {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.group-label {
  width: 72px;
  color: #64748b;
  font-size: 0.9rem;
  padding-top: 8px;
  flex-shrink: 0;
}

.chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.chip-btn {
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #334155;
  border-radius: 999px;
  padding: 8px 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.18s ease;
}

.chip-btn:hover {
  transform: translateY(-1px);
  border-color: #cbd5e1;
}

.chip-btn.active {
  background: #111827;
  color: white;
  border-color: #111827;
}

.filter-summary {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  color: #64748b;
  font-size: 0.92rem;
}

.text-reset {
  border: none;
  background: none;
  color: #2563eb;
  font-weight: 700;
  cursor: pointer;
}

.task-grid {
  display: grid;
  gap: 18px;
}

.managed-card {
  background: white;
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid #f4f4f5;
  box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05);
  display: flex;
  transition: transform 0.2s, box-shadow 0.2s;
}

.managed-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 24px -12px rgba(15, 23, 42, 0.25);
}

.card-status-strip { width: 6px; }
.card-status-strip.running, .card-status-strip.extracting { background: #3b82f6; }
.card-status-strip.completed { background: #22c55e; }
.card-status-strip.paused { background: #f59e0b; }
.card-status-strip.failed { background: #ef4444; }
.card-status-strip.cancelled { background: #94a3b8; }
.card-status-strip.pending { background: #64748b; }

.card-main {
  flex: 1;
  padding: 22px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 12px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.task-title {
  font-size: 1.2rem;
  font-weight: 800;
  color: #18181b;
  margin: 0;
}

.type-tag,
.chat-tag {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 0.78rem;
  font-weight: 700;
}

.type-tag.single {
  background: #dbeafe;
  color: #1d4ed8;
}

.type-tag.batch {
  background: #ede9fe;
  color: #6d28d9;
}

.chat-tag {
  background: #f1f5f9;
  color: #475569;
}

.task-meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 0.85rem;
  color: #71717a;
}

.m-icon {
  margin-right: 4px;
  font-style: normal;
}

.status-badge {
  padding: 6px 12px;
  border-radius: 50px;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.status-badge.running, .status-badge.extracting { background: #dbeafe; color: #1e40af; }
.status-badge.completed { background: #dcfce7; color: #166534; }
.status-badge.paused { background: #fef3c7; color: #92400e; }
.status-badge.failed { background: #fee2e2; color: #991b1b; }
.status-badge.cancelled { background: #e2e8f0; color: #475569; }
.status-badge.pending { background: #e2e8f0; color: #334155; }

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

.intent-line {
  color: #475569;
  font-size: 0.95rem;
  margin-bottom: 14px;
}

.error-banner,
.info-banner {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  border-radius: 14px;
  padding: 12px 14px;
  margin-bottom: 14px;
}

.error-banner {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}

.info-banner {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1d4ed8;
}

.error-label,
.info-label {
  font-weight: 800;
  flex-shrink: 0;
}

.error-text,
.info-text {
  word-break: break-word;
}

.progress-section { margin-bottom: 18px; }
.progress-header { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; margin-bottom: 8px; }
.percentage { font-size: 1.45rem; font-weight: 800; color: #18181b; line-height: 1; }
.count { font-size: 0.85rem; color: #71717a; margin-left: 8px; }
.p-right { text-align: right; }
.speed-label { display: block; font-weight: 700; color: #3b82f6; font-size: 0.9rem; }
.size-label { display: block; font-weight: 700; color: #16a34a; font-size: 0.9rem; }

.main-progress-bar { height: 10px; background: #f4f4f5; border-radius: 5px; overflow: hidden; }
.bar-fill { height: 100%; transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1); background: #3b82f6; }
.bar-fill.completed { background: #22c55e; }
.bar-fill.paused { background: #f59e0b; }
.bar-fill.failed { background: #ef4444; }
.bar-fill.cancelled { background: #94a3b8; }

.footer-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.footer-right {
  margin-left: auto;
  display: flex;
  gap: 10px;
}

.loading-state, .empty-state {
  text-align: center;
  padding: 100px 20px;
  color: #71717a;
}

.empty-state.compact {
  padding: 60px 20px;
}

.spinner {
  width: 48px;
  height: 48px;
  border: 4px solid #f4f4f5;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 20px;
}

@keyframes spin { to { transform: rotate(360deg); } }

.empty-icon { font-size: 4rem; margin-bottom: 20px; }
.cta-link { display: inline-flex; margin-top: 20px; text-decoration: none; }

@media (max-width: 960px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .page-header,
  .card-head,
  .progress-header,
  .filter-summary {
    flex-direction: column;
    align-items: stretch;
  }

  .group-label {
    width: auto;
    padding-top: 0;
  }

  .footer-right {
    margin-left: 0;
  }
}

@media (max-width: 640px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .card-main,
  .filter-panel {
    padding: 16px;
  }

  .task-meta,
  .title-row,
  .footer-actions {
    gap: 8px;
  }
}
</style>
