<template>
  <div class="fade-in">
    <div class="page-header">
      <div class="header-text">
        <h1>📋 Task Management</h1>
        <p class="subtitle">Monitor and control your export activities</p>
      </div>
      <router-link to="/export" class="btn-premium">+ New Export</router-link>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <p>Fetching your tasks...</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="tasks.length === 0" class="empty-state">
      <div class="empty-icon">📂</div>
      <h3>Nothing here yet</h3>
      <p>Create your first export task to get started</p>
      <router-link to="/export" class="btn-premium">Create Export</router-link>
    </div>

    <!-- Task Cards -->
    <div v-else class="task-grid">
      <div v-for="task in tasks" :key="task.id" :class="['managed-card', task.status]">
        <div class="card-status-strip" :class="task.status"></div>
        
        <div class="card-main">
          <div class="card-head">
            <div class="task-info">
              <h3 class="task-title">{{ task.name }}</h3>
              <div class="task-meta">
                <span class="meta-item"><i class="m-icon">📅</i> {{ formatDate(task.created_at) }}</span>
                <span class="meta-item"><i class="m-icon">📎</i> {{ task.total_media }} items</span>
              </div>
            </div>
            <div :class="['status-badge', task.status]">
              <span class="pulse-dot" v-if="isRunning(task)"></span>
              {{ getStatusText(task) }}
            </div>
          </div>

          <div class="progress-section">
            <div class="progress-header">
              <div class="p-left">
                <span class="percentage">{{ getProgress(task).toFixed(1) }}%</span>
                <span class="count">{{ task.downloaded_media || 0 }} / {{ task.total_media || 0 }}</span>
              </div>
              <div class="p-right" v-if="isRunning(task) && task.download_speed > 0">
                <span class="speed-label">⚡ {{ formatSpeed(task.download_speed) }}</span>
                <span class="etr">ETR: {{ calculateETR(task) }}</span>
              </div>
            </div>
            <div class="main-progress-bar">
              <div class="bar-fill" :style="{ width: getProgress(task) + '%' }" :class="task.status"></div>
            </div>
          </div>

          <!-- File List Expansion -->
          <div class="files-dropdown">
            <button class="expand-btn" @click="toggleFiles(task.id)">
              <span class="label">Download Queue ({{ task.download_queue?.length || 0 }})</span>
              <i class="chevron" :class="{ rotated: expandedTasks[task.id] }">▼</i>
            </button>
            
            <div v-if="expandedTasks[task.id]" class="file-table-container animate-slide">
              <div class="file-list">
                <div v-for="file in task.download_queue" :key="file.id" class="mini-file-item">
                  <div class="file-icon-box">📄</div>
                  <div class="file-details">
                    <div class="file-row-1">
                      <span class="f-name">{{ file.file_name || 'Processing...' }}</span>
                      <span class="f-size">{{ formatSize(file.file_size) }}</span>
                    </div>
                    <div class="mini-bar">
                      <div class="mini-fill" :style="{ width: (file.progress || 0) + '%' }" :class="file.status"></div>
                    </div>
                  </div>
                  <div class="file-actions">
                    <span :class="['mini-status', file.status]">{{ getFileStatusText(file.status) }}</span>
                    <button 
                      v-if="['failed', 'cancelled', 'paused', 'completed'].includes(file.status)" 
                      @click="retryFile(task.id, file.id)"
                      class="btn-mini-retry"
                      title="Rerun / Retry"
                    >🔄</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="card-footer">
            <div class="footer-actions">
              <template v-if="isRunning(task)">
                <button @click="pauseTask(task.id)" class="btn-f-action pause">⏸ Pause</button>
              </template>
              <template v-else>
                <button @click="resumeTask(task.id)" class="btn-f-action resume">
                  {{ task.status === 'completed' ? '🚀 Rerun' : '▶ Resume' }}
                </button>
              </template>
              
              <button 
                v-if="getFailedCount(task) > 0" 
                @click="retryAllFailed(task.id)" 
                class="btn-f-action retry"
              >🔄 Retry Failed ({{ getFailedCount(task) }})</button>

              <div class="footer-right">
                <a 
                  v-if="task.status === 'completed'" 
                  :href="'/exports/' + task.id" 
                  target="_blank" 
                  class="btn-f-action open"
                >📂 Browse</a>
                
                <button 
                  v-if="!isRunning(task)" 
                  @click="deleteTask(task.id)" 
                  class="btn-f-action delete"
                >🗑 Delete</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

const loading = ref(true)
const tasks = ref([])
const expandedTasks = ref({})
let refreshTimer = null

function getAuthHeader() {
  return { Authorization: `Bearer ${localStorage.getItem('token')}` }
}

async function fetchTasks() {
  try {
    const res = await axios.get('/api/export/tasks', { headers: getAuthHeader() })
    tasks.value = res.data.reverse()
  } catch (err) {
    console.error('Fetch tasks failed:', err)
  } finally {
    loading.value = false
  }
}

async function pauseTask(taskId) {
  try {
    await axios.post(`/api/export/${taskId}/pause`, {}, { headers: getAuthHeader() })
    await fetchTasks()
  } catch (err) {
    alert('Pause failed: ' + (err.response?.data?.detail || err.message))
  }
}

async function resumeTask(taskId) {
  try {
    const task = tasks.value.find(t => t.id === taskId)
    const action = task.status === 'completed' ? 'Rerunning' : 'Resuming'
    await axios.post(`/api/export/${taskId}/resume`, {}, { headers: getAuthHeader() })
    await fetchTasks()
  } catch (err) {
    alert('Action failed: ' + (err.response?.data?.detail || err.message))
  }
}

async function deleteTask(taskId) {
  if (!confirm('Are you sure you want to delete this task?')) return
  try {
    await axios.delete(`/api/export/${taskId}`, { headers: getAuthHeader() })
    tasks.value = tasks.value.filter(t => t.id !== taskId)
  } catch (err) {
    alert('Delete failed: ' + (err.response?.data?.detail || err.message))
  }
}

async function retryFile(taskId, fileId) {
  try {
    await axios.post(`/api/export/${taskId}/retry/${fileId}`, {}, { headers: getAuthHeader() })
    await fetchTasks()
  } catch (err) {
    alert('Retry failed: ' + (err.response?.data?.detail || err.message))
  }
}

async function retryAllFailed(taskId) {
  try {
    await axios.post(`/api/export/${taskId}/retry`, {}, { headers: getAuthHeader() })
    await fetchTasks()
  } catch (err) {
    alert('Retry failed: ' + (err.response?.data?.detail || err.message))
  }
}

function toggleFiles(taskId) {
  expandedTasks.value[taskId] = !expandedTasks.value[taskId]
}

function isRunning(task) {
  return ['running', 'extracting', 'pending'].includes(task.status)
}

function getProgress(task) {
  if (!task.total_media || task.total_media === 0) return task.status === 'completed' ? 100 : 0
  return ((task.downloaded_media || 0) / task.total_media) * 100
}

function getFailedCount(task) {
  if (!task.download_queue) return 0
  return task.download_queue.filter(f => f.status === 'failed').length
}

function calculateETR(task) {
  if (!task.download_speed || task.download_speed <= 0) return 'Scanning...'
  
  // Calculate remaining size based on the entire queue (rough estimate)
  // Logic: avg file size * (total - downloaded)
  const remainingCount = task.total_media - task.downloaded_media
  if (remainingCount <= 0) return 'Finished'
  
  // Simple remaining size estimate if back-end doesn't provide total_size_diff
  // but we have downloaded_size and total_media
  const avgFileSize = task.downloaded_size / Math.max(1, task.downloaded_media)
  const estimatedRemainingSize = avgFileSize * remainingCount
  
  const seconds = estimatedRemainingSize / task.download_speed
  if (!isFinite(seconds) || seconds < 0) return '...'
  
  if (seconds > 3600) return `${(seconds / 3600).toFixed(1)}h remaining`
  if (seconds > 60) return `${(seconds / 60).toFixed(0)}m remaining`
  return `${seconds.toFixed(0)}s remaining`
}

function getStatusText(task) {
  const texts = {
    pending: 'Waiting',
    extracting: 'Scanning History',
    running: 'Downloading',
    paused: 'Paused',
    completed: 'Finished',
    failed: 'Failed',
    cancelled: 'Stopped'
  }
  return texts[task.status] || task.status
}

function getFileStatusText(status) {
  const texts = {
    waiting: 'Wait',
    downloading: 'Transfer',
    completed: 'Done',
    failed: 'Err',
    paused: 'Hold',
    skipped: 'Skip'
  }
  return texts[status] || status
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString()
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
.card-status-strip.running { background: #3b82f6; }
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

.status-badge.running { background: #dbeafe; color: #1e40af; }
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
.speed-label { display: block; font-weight: 700; color: #166534; font-size: 0.9rem; }
.etr { font-size: 0.75rem; color: #71717a; }

.main-progress-bar { height: 10px; background: #f4f4f5; border-radius: 5px; overflow: hidden; }
.bar-fill { height: 100%; transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1); background: #3b82f6; }
.bar-fill.completed { background: #22c55e; }
.bar-fill.paused { background: #f59e0b; }
.bar-fill.failed { background: #ef4444; }

/* Files Dropdown */
.files-dropdown { margin-bottom: 20px; border: 1px solid #f4f4f5; border-radius: 12px; overflow: hidden; }
.expand-btn {
  width: 100%;
  padding: 12px 16px;
  background: #fafafa;
  border: none;
  display: flex;
  justify-content: space-between;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 600;
  color: #52525b;
}

.chevron { transition: transform 0.3s; font-style: normal; display: inline-block; }
.chevron.rotated { transform: rotate(180deg); }

.file-list { max-height: 240px; overflow-y: auto; padding: 0 8px; }

.mini-file-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 8px;
  border-bottom: 1px solid #f4f4f5;
}

.mini-file-item:last-child { border: none; }
.file-icon-box { background: #f4f4f5; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; border-radius: 8px; }

.file-details { flex: 1; min-width: 0; }
.file-row-1 { display: flex; justify-content: space-between; margin-bottom: 4px; }
.f-name { font-size: 0.75rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.f-size { font-size: 0.7rem; color: #a1a1aa; }

.mini-bar { height: 4px; background: #f4f4f5; border-radius: 2px; overflow: hidden; }
.mini-fill { height: 100%; background: #3b82f6; }
.mini-fill.completed { background: #22c55e; }
.mini-fill.failed { background: #ef4444; }

.file-actions { display: flex; align-items: center; gap: 8px; }
.mini-status { font-size: 0.65rem; font-weight: 800; text-transform: uppercase; padding: 2px 6px; border-radius: 4px; }
.mini-status.completed { background: #dcfce7; color: #166534; }
.mini-status.downloading { background: #dbeafe; color: #1e40af; }

.btn-mini-retry { background: none; border: none; cursor: pointer; opacity: 0.6; transition: 0.2s; }
.btn-mini-retry:hover { opacity: 1; transform: rotate(45deg); }

/* Footer Actions */
.footer-actions { display: flex; gap: 10px; align-items: center; }
.btn-f-action {
  padding: 8px 16px;
  border-radius: 10px;
  border: none;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-f-action.pause { background: #fff7ed; color: #9a3412; }
.btn-f-action.resume { background: #f0fdf4; color: #166534; }
.btn-f-action.retry { background: #eff6ff; color: #1e40af; }
.btn-f-action.open { background: #fdf4ff; color: #701a75; text-decoration: none; }
.btn-f-action.delete { background: #fef2f2; color: #991b1b; }

.footer-right { margin-left: auto; display: flex; gap: 10px; }

.loading-state, .empty-state { text-align: center; padding: 100px 20px; color: #71717a; }
.spinner { width: 48px; height: 48px; border: 4px solid #f4f4f5; border-top-color: var(--primary); border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px; }
@keyframes spin { to { transform: rotate(360deg); } }
.empty-icon { font-size: 4rem; margin-bottom: 20px; }

.animate-slide {
  animation: slideDown 0.3s ease-out;
}
</style>
