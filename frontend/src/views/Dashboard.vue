<template>
  <div class="fade-in dashboard-page">
    <div class="page-header dashboard-header">
      <div>
        <div class="eyebrow">Overview</div>
        <h1>📊 仪表盘</h1>
        <p class="subtitle">Telegram 导出任务概览，优先显示连接状态、最近任务与下一步操作。</p>
      </div>
      <div class="connection-pill" :class="{ connected: telegramStatus.authorized }">
        <span class="indicator"></span>
        {{ telegramStatus.authorized ? 'Telegram 已连接' : '未连接' }}
      </div>
    </div>

    <div class="stats-container">
      <div class="stat-glass-card primary">
        <div class="s-icon">📦</div>
        <div class="s-data">
          <div class="s-value">{{ stats.totalTasks }}</div>
          <div class="s-label">任务总数</div>
        </div>
      </div>
      <div class="stat-glass-card success">
        <div class="s-icon">✅</div>
        <div class="s-data">
          <div class="s-value">{{ stats.completedTasks }}</div>
          <div class="s-label">已完成</div>
        </div>
      </div>
      <div class="stat-glass-card info">
        <div class="s-icon">⚡</div>
        <div class="s-data">
          <div class="s-value">{{ stats.runningTasks }}</div>
          <div class="s-label">进行中</div>
        </div>
      </div>
    </div>

    <div class="dashboard-shell">
      <div class="dashboard-main">
        <div class="premium-card recent-card">
          <div class="p-card-head compact-head">
            <div>
              <div class="eyebrow">Recent activity</div>
              <h3>🕒 最近活动</h3>
            </div>
            <router-link to="/tasks" class="text-link">查看全部任务 →</router-link>
          </div>

          <div class="filter-bar">
            <button class="filter-chip" :class="{ active: taskFilter === 'all' }" @click="taskFilter = 'all'">全部</button>
            <button class="filter-chip" :class="{ active: taskFilter === 'single' }" @click="taskFilter = 'single'">🎯 单文件</button>
            <button class="filter-chip" :class="{ active: taskFilter === 'batch' }" @click="taskFilter = 'batch'">📦 批量</button>
            <button class="filter-chip" :class="{ active: taskFilter === 'failed' }" @click="taskFilter = 'failed'">❌ 失败</button>
          </div>

          <div v-if="filteredRecentTasks.length === 0" class="empty-table enhanced-empty">
            <div class="empty-icon">🫧</div>
            <p>暂无符合条件的任务</p>
          </div>

          <div v-else class="task-list-grid">
            <button v-for="task in filteredRecentTasks" :key="task.id" class="task-list-card" @click="goToDetail(task.id)">
              <div class="task-card-head">
                <div>
                  <div class="task-name">{{ task.name }}</div>
                  <div class="task-intent">{{ formatTaskIntent(task) }}</div>
                </div>
                <span :class="['status-pill', task.status]">{{ statusText[task.status] || task.status }}</span>
              </div>
              <div class="task-progress-row">
                <div class="row-progress-bar">
                  <div class="row-fill" :style="{ width: task.progress + '%' }" :class="task.status"></div>
                </div>
                <span class="row-percent">{{ (task.progress || 0).toFixed(0) }}%</span>
              </div>
              <div class="task-footer-meta">{{ formatDate(task.created_at) }}</div>
            </button>
          </div>
        </div>
      </div>

      <aside class="dashboard-side">
        <div class="premium-card session-card">
          <div class="p-card-head compact-head">
            <div>
              <div class="eyebrow">Session</div>
              <h3>👤 会话详情</h3>
            </div>
            <button @click="refreshStatus" class="btn-icon-only">🔄</button>
          </div>

          <div v-if="loading" class="card-loading">
            <div class="skeleton-avatar"></div>
            <div class="skeleton-text"></div>
          </div>

          <div v-else-if="telegramStatus.authorized" class="user-profile animate-slide">
            <div class="user-avatar">{{ telegramStatus.user?.first_name?.[0] || '?' }}</div>
            <div class="user-info">
              <div class="u-name">{{ telegramStatus.user?.first_name }} {{ telegramStatus.user?.last_name }}</div>
              <div class="u-handle">@{{ telegramStatus.user?.username || '无用户名' }}</div>
              <div class="u-id">UID: {{ telegramStatus.user?.id }}</div>
            </div>
            <div class="u-verified-badge">✓ 已验证会话</div>
          </div>

          <div v-else class="auth-required enhanced-empty small-empty">
            <div class="empty-mini-icon">🚫</div>
            <p>请先登录您的 Telegram 账号以开始导出任务。</p>
            <router-link to="/settings" class="btn-premium sm">前往设置</router-link>
          </div>
        </div>

        <div class="premium-card actions-card">
          <div class="p-card-head compact-head">
            <div>
              <div class="eyebrow">Actions</div>
              <h3>⚡ 快速操作</h3>
            </div>
          </div>
          <div class="action-tiles vertical-tiles">
            <router-link to="/export" class="action-tile purple">
              <span class="t-icon">📥</span>
              <span class="tile-copy">
                <strong>新建导出</strong>
                <small>开始新的历史记录或文件导出任务</small>
              </span>
            </router-link>
            <router-link to="/tasks" class="action-tile blue">
              <span class="t-icon">📋</span>
              <span class="tile-copy">
                <strong>下载管理</strong>
                <small>查看失败任务、进度和最近导出</small>
              </span>
            </router-link>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

const router = useRouter()
const loading = ref(true)
const telegramStatus = ref({ authorized: false, user: null })
const recentTasks = ref([])
const taskFilter = ref('all')
const stats = ref({ totalTasks: 0, completedTasks: 0, runningTasks: 0, totalSize: 0 })

const statusText = {
  extracting: '正在扫描',
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已停止'
}

const filteredRecentTasks = computed(() => {
  if (taskFilter.value === 'all') return recentTasks.value
  if (taskFilter.value === 'single') return recentTasks.value.filter(t => (t.options?.message_to > 0 && t.options?.message_from === t.options?.message_to))
  if (taskFilter.value === 'batch') return recentTasks.value.filter(t => !(t.options?.message_to > 0 && t.options?.message_from === t.options?.message_to))
  if (taskFilter.value === 'failed') return recentTasks.value.filter(t => t.status === 'failed')
  return recentTasks.value
})

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
    const tasks = tasksRes.data
    stats.value = {
      totalTasks: tasks.length,
      completedTasks: tasks.filter(t => t.status === 'completed').length,
      runningTasks: tasks.filter(t => ['running', 'extracting', 'pending'].includes(t.status)).length,
      totalSize: tasks.reduce((sum, t) => sum + (t.downloaded_size || 0), 0)
    }
  } catch (err) {
    console.error('Refresh failed:', err)
  } finally {
    loading.value = false
  }
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN')
}

function goToDetail(id) {
  router.push(`/tasks/${id}`)
}

function formatTaskIntent(task) {
  const opts = task.options || {}
  const chatPart = (opts.specific_chats && opts.specific_chats.length === 1)
    ? `频道 ${opts.specific_chats[0]}`
    : (opts.specific_chats && opts.specific_chats.length > 1)
      ? `指定 ${opts.specific_chats.length} 个聊天`
      : '自动范围'

  const rangePart = opts.message_to > 0 ? `${opts.message_from}-${opts.message_to}` : `${opts.message_from}-最新`
  const modePart = opts.message_to > 0 && opts.message_from === opts.message_to ? '🎯 单消息任务' : '📦 批量任务'
  return `${modePart} · ${chatPart} · ${rangePart}`
}

onMounted(refreshStatus)
</script>

<style scoped>
.dashboard-page { display: flex; flex-direction: column; gap: 18px; }
.dashboard-header { align-items: flex-start; gap: 16px; margin-bottom: 0; }
.eyebrow { font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--primary-dark); font-weight: 700; margin-bottom: 6px; }
.subtitle { color: #71717a; font-size: 1rem; }
.connection-pill { padding: 8px 16px; background: rgba(255,255,255,0.65); border-radius: 999px; border: 1px solid rgba(17,24,39,0.08); -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px); font-size: 0.85rem; font-weight: 700; display: flex; align-items: center; gap: 8px; color: #71717a; }
.connection-pill.connected { background: #dcfce7; color: #166534; }
.connection-pill .indicator { width: 8px; height: 8px; border-radius: 50%; background: #a1a1aa; }
.connection-pill.connected .indicator { background: #22c55e; box-shadow: 0 0 10px #22c55e; }
.stats-container { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.stat-glass-card { padding: 24px; border-radius: 24px; background: rgba(255,255,255,0.82); border: 1px solid rgba(17,24,39,0.08); display: flex; align-items: center; gap: 18px; -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); box-shadow: 0 18px 40px -26px rgba(15,23,42,0.35); }
.s-icon { width: 56px; height: 56px; border-radius: 16px; display: flex; align-items: center; justify-content: center; font-size: 1.5rem; background: #f4f4f5; }
.stat-glass-card.primary .s-icon { background: #eff6ff; }
.stat-glass-card.success .s-icon { background: #f0fdf4; }
.stat-glass-card.info .s-icon { background: #fdf4ff; }
.s-value { font-size: 1.75rem; font-weight: 800; color: #18181b; line-height: 1.2; }
.s-label { font-size: 0.85rem; color: #71717a; font-weight: 600; }
.dashboard-shell { display: grid; grid-template-columns: minmax(0, 1.4fr) 360px; gap: 20px; align-items: start; }
.dashboard-side { display: flex; flex-direction: column; gap: 20px; }
.premium-card { background: rgba(255,255,255,0.82); border-radius: 24px; padding: 24px; border: 1px solid rgba(17,24,39,0.08); -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); box-shadow: 0 18px 40px -26px rgba(15,23,42,0.35); }
.compact-head { margin-bottom: 18px; }
.p-card-head { display: flex; justify-content: space-between; align-items: center; }
.task-list-grid { display: grid; gap: 14px; }
.task-list-card { text-align: left; border: 1px solid #eef2f7; background: #fff; border-radius: 18px; padding: 16px; cursor: pointer; transition: 0.2s; }
.task-list-card:hover { transform: translateY(-2px); box-shadow: 0 18px 40px -30px rgba(15,23,42,0.42); }
.task-list-card:active { transform: translateY(0px) scale(0.995); }
.task-card-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 12px; }
.task-name { font-weight: 800; color: #18181b; margin-bottom: 4px; }
.task-intent { color: #64748b; font-size: 13px; }
.task-progress-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.row-progress-bar { flex: 1; height: 8px; background: #f1f5f9; border-radius: 999px; overflow: hidden; }
.row-fill { height: 100%; background: #3b82f6; }
.row-fill.completed { background: #22c55e; }
.row-fill.failed { background: #ef4444; }
.row-fill.cancelled { background: #94a3b8; }
.row-percent, .task-footer-meta { color: #64748b; font-size: 12px; }
.filter-bar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.filter-chip { border: 1px solid #e2e8f0; background: #fff; border-radius: 999px; padding: 8px 14px; cursor: pointer; font-weight: 600; }
.filter-chip.active { background: #111827; color: #fff; border-color: #111827; }
.filter-chip:active { transform: scale(0.99); }
.user-profile { display: flex; align-items: center; gap: 18px; padding: 16px; background: #fafafa; border-radius: 20px; position: relative; }
.user-avatar { width: 64px; height: 64px; border-radius: 50%; background: linear-gradient(135deg, var(--primary), #a855f7); display: flex; align-items: center; justify-content: center; color: white; font-size: 1.5rem; font-weight: 800; box-shadow: 0 8px 16px -4px rgba(168, 85, 247, 0.4); }
.user-info { flex: 1; }
.u-name { font-weight: 700; font-size: 1.1rem; }
.u-handle { color: var(--primary); font-weight: 600; font-size: 0.9rem; }
.u-id { color: #a1a1aa; font-size: 0.75rem; margin-top: 4px; }
.u-verified-badge { position: absolute; top: -10px; right: 16px; background: #22c55e; color: white; padding: 4px 10px; border-radius: 50px; font-size: 0.7rem; font-weight: 800; }
.vertical-tiles { grid-template-columns: 1fr; }
.action-tiles { display: grid; gap: 12px; }
.action-tile { display: flex; align-items: center; gap: 14px; padding: 18px; border-radius: 20px; text-decoration: none; transition: all 0.2s; }
.action-tile:hover { transform: translateY(-2px); }
.action-tile:active { transform: translateY(0px) scale(0.995); }
.action-tile.purple { background: #fdf4ff; color: #701a75; }
.action-tile.blue { background: #eff6ff; color: #1e40af; }
.tile-copy { display: flex; flex-direction: column; }
.tile-copy small { opacity: 0.8; }
.t-icon { font-size: 1.5rem; }
.enhanced-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 32px 16px; color: #64748b; }
.empty-icon { font-size: 2rem; margin-bottom: 10px; }
.small-empty { text-align: center; }
@media (max-width: 1100px) {
  .dashboard-shell { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .dashboard-header, .task-card-head { flex-direction: column; align-items: stretch; }
  .stats-container { grid-template-columns: 1fr; }
  .premium-card, .stat-glass-card { padding: 18px; }
}
</style>
