<template>
  <div class="tasks-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <h1>📋 任务管理</h1>
      <router-link to="/export" class="btn-primary">+ 新建导出</router-link>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- 空状态 -->
    <div v-else-if="tasks.length === 0" class="empty-state">
      <div class="empty-icon">📭</div>
      <p>暂无任务</p>
      <router-link to="/export" class="btn-primary">创建第一个导出任务</router-link>
    </div>

    <!-- 任务列表 -->
    <div v-else class="task-list">
      <div v-for="task in tasks" :key="task.id" class="task-card">
        <!-- 任务头部 -->
        <div class="task-header">
          <div class="task-info">
            <h3 class="task-name">{{ task.name }}</h3>
            <span class="task-time">{{ formatDate(task.created_at) }}</span>
          </div>
          <span :class="['task-status', getStatusClass(task)]">
            {{ getStatusText(task) }}
          </span>
        </div>

        <!-- 总进度条 -->
        <div class="task-progress">
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: getProgress(task) + '%' }"></div>
          </div>
          <div class="progress-stats">
            <span>{{ task.downloaded_media || 0 }}/{{ task.total_media || 0 }} 文件</span>
            <span>{{ formatSize(task.downloaded_size) }}</span>
            <span v-if="isRunning(task) && task.download_speed > 0" class="speed">
              ⚡ {{ formatSpeed(task.download_speed) }}
            </span>
            <span v-if="getFailedCount(task) > 0" class="failed-count">
              ⚠️ {{ getFailedCount(task) }} 失败
            </span>
          </div>
        </div>

        <!-- 文件列表 (可展开) -->
        <div v-if="task.download_queue && task.download_queue.length > 0" class="file-section">
          <div class="file-header" @click="toggleFiles(task.id)">
            <span>📥 下载列表 ({{ task.download_queue.length }})</span>
            <span class="toggle">{{ expandedTasks[task.id] ? '▼' : '▶' }}</span>
          </div>
          
          <div v-if="expandedTasks[task.id]" class="file-list">
            <div v-for="file in task.download_queue" :key="file.id" class="file-item">
              <div class="file-info">
                <div class="file-name-row">
                  <span class="file-name">{{ file.file_name || '未知文件' }}</span>
                  <span class="file-size">{{ formatSize(file.downloaded_size) }} / {{ formatSize(file.file_size) }}</span>
                </div>
                <div class="file-progress-bar">
                  <div class="file-progress-fill" :style="{ width: (file.progress || 0) + '%' }"></div>
                </div>
              </div>
              <div class="file-status">
                <span v-if="file.status === 'downloading' && file.speed > 0" class="file-speed">
                  {{ formatSpeed(file.speed) }}
                </span>
                <span class="file-percent">{{ (file.progress || 0).toFixed(0) }}%</span>
                <span :class="['file-state', 'state-' + file.status]">
                  {{ getFileStatusText(file.status) }}
                </span>
                <button 
                  v-if="['failed', 'cancelled', 'paused'].includes(file.status)" 
                  @click="retryFile(task.id, file.id)"
                  class="btn-retry"
                  title="重试"
                >🔄</button>
              </div>
            </div>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="task-actions">
          <button 
            v-if="isRunning(task)" 
            @click="pauseTask(task.id)" 
            class="btn-action btn-pause"
          >⏸ 暂停</button>
          
          <button 
            v-if="['paused', 'cancelled', 'failed'].includes(task.status)" 
            @click="resumeTask(task.id)" 
            class="btn-action btn-resume"
          >▶ 继续</button>
          
          <button 
            v-if="getFailedCount(task) > 0" 
            @click="retryAllFailed(task.id)" 
            class="btn-action btn-retry-all"
          >🔄 重试失败 ({{ getFailedCount(task) }})</button>
          
          <a 
            v-if="task.status === 'completed'" 
            :href="'/exports/' + task.id" 
            target="_blank" 
            class="btn-action btn-folder"
          >📂 打开</a>
          
          <button 
            v-if="!isRunning(task)" 
            @click="deleteTask(task.id)" 
            class="btn-action btn-delete"
          >🗑 删除</button>
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

// 获取认证头
function getAuthHeader() {
  return { Authorization: `Bearer ${localStorage.getItem('token')}` }
}

// 加载任务列表
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

// 暂停任务
async function pauseTask(taskId) {
  try {
    await axios.post(`/api/export/${taskId}/pause`, {}, { headers: getAuthHeader() })
    await fetchTasks()
  } catch (err) {
    alert('暂停失败: ' + (err.response?.data?.detail || err.message))
  }
}

// 恢复任务
async function resumeTask(taskId) {
  try {
    await axios.post(`/api/export/${taskId}/resume`, {}, { headers: getAuthHeader() })
    await fetchTasks()
  } catch (err) {
    alert('恢复失败: ' + (err.response?.data?.detail || err.message))
  }
}

// 删除任务
async function deleteTask(taskId) {
  if (!confirm('确定要删除此任务吗？')) return
  try {
    await axios.delete(`/api/export/${taskId}`, { headers: getAuthHeader() })
    tasks.value = tasks.value.filter(t => t.id !== taskId)
  } catch (err) {
    alert('删除失败: ' + (err.response?.data?.detail || err.message))
  }
}

// 重试单个文件
async function retryFile(taskId, fileId) {
  try {
    await axios.post(`/api/export/${taskId}/retry/${fileId}`, {}, { headers: getAuthHeader() })
    await fetchTasks()
  } catch (err) {
    alert('重试失败: ' + (err.response?.data?.detail || err.message))
  }
}

// 重试所有失败文件
async function retryAllFailed(taskId) {
  try {
    await axios.post(`/api/export/${taskId}/retry`, {}, { headers: getAuthHeader() })
    await fetchTasks()
  } catch (err) {
    alert('重试失败: ' + (err.response?.data?.detail || err.message))
  }
}

// 切换文件列表展开
function toggleFiles(taskId) {
  expandedTasks.value[taskId] = !expandedTasks.value[taskId]
}

// 辅助函数
function isRunning(task) {
  return ['running', 'extracting', 'pending'].includes(task.status)
}

function getProgress(task) {
  if (!task.total_media || task.total_media === 0) {
    return task.status === 'completed' ? 100 : 0
  }
  return ((task.downloaded_media || 0) / task.total_media) * 100
}

function getFailedCount(task) {
  if (!task.download_queue) return 0
  return task.download_queue.filter(f => f.status === 'failed').length
}

function getStatusClass(task) {
  if (isRunning(task)) return 'status-running'
  if (task.status === 'paused') return 'status-paused'
  if (task.status === 'completed') return 'status-completed'
  return 'status-other'
}

function getStatusText(task) {
  const texts = {
    pending: '准备中',
    extracting: '扫描中',
    running: '下载中',
    paused: '已暂停',
    completed: '已完成',
    failed: '失败',
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
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024
    i++
  }
  return bytes.toFixed(1) + ' ' + units[i]
}

function formatSpeed(bytesPerSecond) {
  if (!bytesPerSecond || bytesPerSecond < 0) return ''
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
  let i = 0
  while (bytesPerSecond >= 1024 && i < units.length - 1) {
    bytesPerSecond /= 1024
    i++
  }
  return bytesPerSecond.toFixed(1) + ' ' + units[i]
}

onMounted(() => {
  fetchTasks()
  // 每3秒刷新
  refreshTimer = setInterval(() => {
    if (tasks.value.some(t => isRunning(t) || t.status === 'paused')) {
      fetchTasks()
    }
  }, 3000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<style scoped>
.tasks-page {
  padding: 20px;
  max-width: 900px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-header h1 {
  margin: 0;
  font-size: 24px;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: white;
  padding: 10px 20px;
  border-radius: 8px;
  text-decoration: none;
  font-weight: 500;
}

/* 加载和空状态 */
.loading-state, .empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #666;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #eee;
  border-top-color: #667eea;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 16px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.empty-icon {
  font-size: 64px;
  margin-bottom: 16px;
}

/* 任务卡片 */
.task-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.task-card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  overflow: hidden;
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 16px 20px;
  background: #fafbfc;
  border-bottom: 1px solid #eee;
}

.task-name {
  margin: 0 0 4px 0;
  font-size: 16px;
  font-weight: 600;
}

.task-time {
  font-size: 12px;
  color: #888;
}

.task-status {
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
}

.status-running { background: #e3f2fd; color: #1976d2; }
.status-paused { background: #fff3e0; color: #ef6c00; }
.status-completed { background: #e8f5e9; color: #2e7d32; }
.status-other { background: #f5f5f5; color: #666; }

/* 进度条 */
.task-progress {
  padding: 16px 20px;
}

.progress-bar {
  height: 8px;
  background: #e8e8e8;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #4facfe, #00f2fe);
  border-radius: 4px;
  transition: width 0.3s ease;
}

.progress-stats {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: #666;
}

.failed-count {
  color: #e53935;
}

.speed {
  color: #2e7d32;
  font-weight: 500;
}

.file-speed {
  color: #2e7d32;
  font-size: 11px;
  margin-right: 4px;
}

/* 文件列表 */
.file-section {
  border-top: 1px solid #eee;
}

.file-header {
  display: flex;
  justify-content: space-between;
  padding: 12px 20px;
  background: #f8f9fa;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
}

.file-header:hover {
  background: #f0f1f2;
}

.toggle {
  color: #888;
}

.file-list {
  max-height: 300px;
  overflow-y: auto;
}

.file-item {
  display: flex;
  align-items: center;
  padding: 10px 20px;
  border-bottom: 1px solid #f0f0f0;
  gap: 12px;
}

.file-item:last-child {
  border-bottom: none;
}

.file-info {
  flex: 1;
  min-width: 0;
}

.file-name-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.file-name {
  font-size: 12px;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

.file-size {
  font-size: 11px;
  color: #888;
  margin-left: 8px;
  white-space: nowrap;
}

.file-progress-bar {
  height: 4px;
  background: #e8e8e8;
  border-radius: 2px;
  overflow: hidden;
}

.file-progress-fill {
  height: 100%;
  background: #4facfe;
  transition: width 0.3s ease;
}

.file-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-percent {
  font-size: 11px;
  color: #888;
  min-width: 35px;
}

.file-state {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
}

.state-waiting { background: #f5f5f5; color: #888; }
.state-downloading { background: #e3f2fd; color: #1976d2; }
.state-completed { background: #e8f5e9; color: #2e7d32; }
.state-failed { background: #ffebee; color: #c62828; }
.state-paused { background: #fff3e0; color: #ef6c00; }
.state-skipped { background: #fafafa; color: #999; }

.btn-retry {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  padding: 2px 4px;
}

.btn-retry:hover {
  background: #f0f0f0;
  border-radius: 4px;
}

/* 操作按钮 */
.task-actions {
  display: flex;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid #eee;
  background: #fafbfc;
}

.btn-action {
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.btn-pause { background: #fff3e0; color: #ef6c00; }
.btn-resume { background: #e8f5e9; color: #2e7d32; }
.btn-retry-all { background: #e3f2fd; color: #1976d2; }
.btn-folder { background: #f3e5f5; color: #7b1fa2; }
.btn-delete { background: #ffebee; color: #c62828; }

.btn-action:hover {
  filter: brightness(0.95);
}
</style>
