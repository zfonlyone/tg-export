<template>
  <div class="fade-in">
    <div class="page-header">
      <div class="header-text">
        <h1>📊 Dashboard</h1>
        <p class="subtitle">Overview of your Telegram archival operations</p>
      </div>
      <div class="connection-pill" :class="{ connected: telegramStatus.authorized }">
        <span class="indicator"></span>
        {{ telegramStatus.authorized ? 'Telegram Connected' : 'Disconnected' }}
      </div>
    </div>
    
    <!-- Hero Stats Section -->
    <div class="stats-container">
      <div class="stat-glass-card primary">
        <div class="s-icon">📦</div>
        <div class="s-data">
          <div class="s-value">{{ stats.totalTasks }}</div>
          <div class="s-label">Total Tasks</div>
        </div>
      </div>
      <div class="stat-glass-card success">
        <div class="s-icon">✅</div>
        <div class="s-data">
          <div class="s-value">{{ stats.completedTasks }}</div>
          <div class="s-label">Completed</div>
        </div>
      </div>
      <div class="stat-glass-card info">
        <div class="s-icon">⚡</div>
        <div class="s-data">
          <div class="s-value">{{ stats.runningTasks }}</div>
          <div class="s-label">Active</div>
        </div>
      </div>
      <div class="stat-glass-card warning">
        <div class="s-icon">💾</div>
        <div class="s-data">
          <div class="s-value">{{ formatSize(stats.totalSize) }}</div>
          <div class="s-label">Data Saved</div>
        </div>
      </div>
    </div>
    
    <div class="dashboard-grid">
      <!-- Session Card -->
      <div class="premium-card session-card">
        <div class="p-card-head">
          <h3>👤 Session Profile</h3>
          <button @click="refreshStatus" class="btn-icon-only">🔄</button>
        </div>
        
        <div v-if="loading" class="card-loading">
          <div class="skeleton-avatar"></div>
          <div class="skeleton-text"></div>
        </div>
        
        <div v-else-if="telegramStatus.authorized" class="user-profile animate-slide">
          <div class="user-avatar">
            {{ telegramStatus.user?.first_name?.[0] || '?' }}
          </div>
          <div class="user-info">
            <div class="u-name">{{ telegramStatus.user?.first_name }} {{ telegramStatus.user?.last_name }}</div>
            <div class="u-handle">@{{ telegramStatus.user?.username || 'no_handle' }}</div>
            <div class="u-id">UID: {{ telegramStatus.user?.id }}</div>
          </div>
          <div class="u-verified-badge">✓ Verified Session</div>
        </div>
        
        <div v-else class="auth-required">
          <div class="empty-mini-icon">🚫</div>
          <p>Login to your Telegram account to start exporting messages.</p>
          <router-link to="/settings" class="btn-premium sm">Go to Settings</router-link>
        </div>
      </div>

      <!-- Quick Actions -->
      <div class="premium-card actions-card">
        <div class="p-card-head"><h3>⚡ Quick Actions</h3></div>
        <div class="action-tiles">
          <router-link to="/export" class="action-tile purple">
            <span class="t-icon">📥</span>
            <span class="t-label">New Export</span>
          </router-link>
          <router-link to="/downloads" class="action-tile blue">
            <span class="t-icon">📋</span>
            <span class="t-label">Downloads</span>
          </router-link>
          <a href="/exports" target="_blank" class="action-tile green">
            <span class="t-icon">📂</span>
            <span class="t-label">Browse Files</span>
          </a>
        </div>
      </div>

      <!-- Recent Tasks -->
      <div class="premium-card table-card full-width">
        <div class="p-card-head">
          <h3>🕒 Recent Activity</h3>
          <router-link to="/downloads" class="text-link">View all tasks →</router-link>
        </div>
        
        <div v-if="recentTasks.length === 0" class="empty-table">
          <p>No task history found</p>
        </div>
        
        <div v-else class="table-wrapper">
          <table class="modern-table">
            <thead>
              <tr>
                <th>Task Name</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="task in recentTasks" :key="task.id" class="table-row">
                <td class="td-name">{{ task.name }}</td>
                <td>
                  <span :class="['status-pill', task.status]">
                    {{ statusText[task.status] || task.status }}
                  </span>
                </td>
                <td>
                  <div class="row-progress-container">
                    <div class="row-progress-bar">
                      <div class="row-fill" :style="{ width: task.progress + '%' }" :class="task.status"></div>
                    </div>
                    <span class="row-percent">{{ (task.progress || 0).toFixed(0) }}%</span>
                  </div>
                </td>
                <td class="td-time">{{ formatDate(task.created_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
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
  extracting: 'Scanning',
  pending: 'Waiting',
  running: 'Downloading',
  completed: 'Finished',
  failed: 'Failed',
  cancelled: 'Stopped'
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

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++ }
  return bytes.toFixed(1) + ' ' + units[i]
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString()
}

onMounted(refreshStatus)
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 40px;
}

.header-text h1 { font-size: 2.5rem; font-weight: 800; margin-bottom: 8px; }
.subtitle { color: #71717a; font-size: 1.1rem; }

.connection-pill {
  padding: 8px 16px;
  background: #f4f4f5;
  border-radius: 50px;
  font-size: 0.85rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #71717a;
}

.connection-pill.connected { background: #dcfce7; color: #166534; }
.connection-pill .indicator { width: 8px; height: 8px; border-radius: 50%; background: #a1a1aa; }
.connection-pill.connected .indicator { background: #22c55e; box-shadow: 0 0 10px #22c55e; }

/* Stats Container */
.stats-container {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 30px;
}

@media (max-width: 1000px) {
  .stats-container { grid-template-columns: repeat(2, 1fr); }
}

.stat-glass-card {
  padding: 24px;
  border-radius: 24px;
  background: white;
  border: 1px solid #f4f4f5;
  display: flex;
  align-items: center;
  gap: 20px;
  box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);
}

.s-icon {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  background: #f4f4f5;
}

.stat-glass-card.primary .s-icon { background: #eff6ff; }
.stat-glass-card.success .s-icon { background: #f0fdf4; }
.stat-glass-card.info .s-icon { background: #fdf4ff; }
.stat-glass-card.warning .s-icon { background: #fffbeb; }

.s-value { font-size: 1.75rem; font-weight: 800; color: #18181b; line-height: 1.2; }
.s-label { font-size: 0.85rem; color: #71717a; font-weight: 600; }

/* Dashboard Grid */
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px;
}

.full-width { grid-column: span 2; }

@media (max-width: 800px) {
  .dashboard-grid { grid-template-columns: 1fr; }
  .full-width { grid-column: span 1; }
}

.premium-card {
  background: white;
  border-radius: 24px;
  padding: 30px;
  border: 1px solid #f4f4f5;
  box-shadow: 0 10px 15px -3px rgba(0,0,0,0.04);
}

.p-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.p-card-head h3 { font-size: 1.1rem; font-weight: 700; color: #18181b; }

/* Session Profile */
.user-profile {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 16px;
  background: #fafafa;
  border-radius: 20px;
  position: relative;
}

.user-avatar {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary), #a855f7);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 1.5rem;
  font-weight: 800;
  box-shadow: 0 8px 16px -4px rgba(168, 85, 247, 0.4);
}

.user-info { flex: 1; }
.u-name { font-weight: 700; font-size: 1.1rem; }
.u-handle { color: var(--primary); font-weight: 600; font-size: 0.9rem; }
.u-id { color: #a1a1aa; font-size: 0.75rem; margin-top: 4px; }

.u-verified-badge {
  position: absolute;
  top: -10px;
  right: 16px;
  background: #22c55e;
  color: white;
  padding: 4px 10px;
  border-radius: 50px;
  font-size: 0.7rem;
  font-weight: 800;
  box-shadow: 0 4px 10px rgba(34, 197, 94, 0.3);
}

/* Action Tiles */
.action-tiles {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.action-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 20px;
  border-radius: 20px;
  text-decoration: none;
  transition: all 0.2s;
}

.action-tile:hover { transform: translateY(-4px); }

.action-tile.purple { background: #fdf4ff; color: #701a75; }
.action-tile.blue { background: #eff6ff; color: #1e40af; }
.action-tile.green { background: #f0fdf4; color: #166534; }

.t-icon { font-size: 1.5rem; }
.t-label { font-size: 0.85rem; font-weight: 700; }

/* Minimal Table */
.table-wrapper { overflow-x: auto; }
.modern-table { width: 100%; border-collapse: separate; border-spacing: 0; }
.modern-table th { text-align: left; padding: 12px 16px; color: #71717a; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
.modern-table td { padding: 16px; border-top: 1px solid #f4f4f5; font-size: 0.9rem; }

.td-name { font-weight: 700; color: #18181b; }
.td-time { color: #a1a1aa; font-size: 0.8rem; }

.status-pill {
  padding: 4px 10px;
  border-radius: 50px;
  font-size: 0.75rem;
  font-weight: 700;
  white-space: nowrap;
}

.status-pill.completed { background: #e8f5e9; color: #2e7d32; }
.status-pill.running, .status-pill.extracting { background: #e3f2fd; color: #1976d2; }
.status-pill.failed { background: #ffebee; color: #c62828; }

.row-progress-container { display: flex; align-items: center; gap: 10px; width: 140px; }
.row-progress-bar { flex: 1; height: 6px; background: #f4f4f5; border-radius: 3px; overflow: hidden; }
.row-fill { height: 100%; transition: width 0.3s; background: #3b82f6; }
.row-fill.completed { background: #22c55e; }
.row-percent { font-size: 0.75rem; font-weight: 700; color: #71717a; width: 35px; }

.text-link { color: var(--primary); font-weight: 600; text-decoration: none; font-size: 0.85rem; }

.btn-icon-only {
  background: none; border: none; cursor: pointer; font-size: 1.2rem;
  transition: transform 0.3s;
}
.btn-icon-only:hover { transform: rotate(180deg); }

.animate-slide { animation: slideUp 0.4s ease-out; }
@keyframes slideUp { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
</style>
