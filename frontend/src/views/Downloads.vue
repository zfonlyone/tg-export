<template>
  <div class="fade-in">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1>📋 任务管理</h1>
      <router-link to="/export" class="btn btn-primary">+ 新建导出</router-link>
    </div>
    
    <!-- 统计卡片 -->
    <div class="stats-row">
      <div class="stat-card completed">
        <div class="stat-icon">✅</div>
        <div class="stat-info">
          <div class="stat-value">{{ completedCount }}</div>
          <div class="stat-label">已完成</div>
        </div>
      </div>
      <div class="stat-card pending">
        <div class="stat-icon">⏳</div>
        <div class="stat-info">
          <div class="stat-value">{{ pendingCount }}</div>
          <div class="stat-label">进行中</div>
        </div>
      </div>
      <div class="stat-card failed">
        <div class="stat-icon">❌</div>
        <div class="stat-info">
          <div class="stat-value">{{ failedCount }}</div>
          <div class="stat-label">异常</div>
        </div>
      </div>
    </div>
    
    <!-- 操作栏 -->
    <div class="actions-bar" v-if="tasks.length > 0">
      <button @click="pauseAll" class="btn btn-outline btn-sm" :disabled="runningCount === 0">
        ⏸ 暂停所有
      </button>
      <button @click="resumeAll" class="btn btn-outline btn-sm" :disabled="pausedCount === 0">
        ▶ 恢复所有
      </button>
      <button @click="removeCompleted" class="btn btn-outline btn-sm" :disabled="completedCount === 0">
        🗑 移除已完成
      </button>
      <span class="refresh-label">更新间隔: {{ refreshInterval / 1000 }}s</span>
    </div>
    
    <!-- 加载中 -->
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
    </div>
    
    <!-- 空状态 -->
    <div v-else-if="tasks.length === 0" class="empty-state">
      <div class="icon">📭</div>
      <p>暂无任务</p>
      <router-link to="/export" class="btn btn-primary">创建第一个导出任务</router-link>
    </div>
    
    <!-- 任务列表 -->
    <div v-else class="task-list">
      <div 
        v-for="task in tasks" 
        :key="task.id" 
        :class="['task-card', task.status]"
      >
        <!-- 任务头部 -->
        <div class="task-header">
          <div>
            <div class="task-title">{{ task.name }}</div>
            <div class="task-meta">创建于 {{ formatDate(task.created_at) }}</div>
          </div>
          <span :class="'status-badge status-' + (task.status === 'extracting' ? 'extracting' : task.status)">
            {{ statusText[task.status] }}
          </span>
        </div>
        
        <!-- 进度条 -->
        <div v-if="['extracting', 'running', 'paused'].includes(task.status)">
          <div class="progress">
            <div class="progress-bar" :style="{ width: task.progress + '%' }"></div>
          </div>
          <div class="progress-text">
            <span>{{ (task.progress || 0).toFixed(1) }}%</span>
            <span v-if="task.status === 'extracting'">🔍 正在扫描消息: {{ task.processed_messages }}</span>
            <span v-else>📥 下载文件: {{ task.downloaded_media }} / {{ task.total_media }}</span>
          </div>
        </div>
        
        <!-- 任务概览信息 -->
        <div class="task-info">
          <div class="task-info-item">
            📨 消息: {{ task.processed_messages }}
          </div>
          <div class="task-info-item">
            📁 媒体: {{ task.downloaded_media }}/{{ task.total_media }}
          </div>
          <div class="task-info-item">
            💾 容量: {{ formatSize(task.downloaded_size) }}
          </div>
          <div class="task-info-item" v-if="task.failed_downloads?.length > 0">
            ⚠️ 失败: {{ task.failed_downloads.length }}
          </div>
        </div>
        
        <!-- 下载清单详情 (运行中默认展开) -->
        <div v-if="task.download_queue?.length > 0" class="failed-section">
          <div class="failed-header" @click="toggleDetailed(task.id)">
            <span>📊 传输明细 ({{ task.downloaded_media }}/{{ task.total_media }})</span>
            <span>{{ isDetailedExpanded(task) ? '▼' : '▶' }}</span>
          </div>
          <div v-if="isDetailedExpanded(task)" class="failed-list">
             <div v-for="item in task.download_queue.slice(0, 50)" :key="item.id" class="download-item-row">
                <div style="flex: 1; min-width: 0;">
                  <div style="display: flex; justify-content: space-between; margin-bottom: 4px; font-size: 11px;">
                    <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: monospace;">{{ item.file_name }}</span>
                    <span>{{ item.progress.toFixed(0) }}%</span>
                  </div>
                  <div class="progress" style="height: 4px; margin: 0; background: rgba(0,0,0,0.05);">
                    <div class="progress-bar" :style="{ width: item.progress + '%' }"></div>
                  </div>
                </div>
                <div style="margin-left: 10px; display: flex; align-items: center; gap: 5px;">
                   <span :class="'item-status ' + item.status">{{ item.status }}</span>
                </div>
             </div>
             <div v-if="task.download_queue.length > 50" class="download-item-row" style="justify-content: center; color: #888; font-size: 12px; border: none;">
                ... 及其他 {{ task.download_queue.length - 50 }} 个文件
             </div>
          </div>
        </div>
        
        <!-- 导出成功 (精简样式) -->
        <div v-if="task.status === 'completed'" class="completed-info-box">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div style="color: #27ae60; font-size: 14px; display: flex; align-items: center; gap: 6px;">
              <span style="font-size: 18px;">✅</span> 导出成功，共计 {{ task.downloaded_media }} 个文件
            </div>
            <a :href="'/exports/' + task.id" target="_blank" class="btn btn-success btn-sm">
              📁 浏览文件
            </a>
          </div>
        </div>
        
        <!-- 错误信息 -->
        <div v-if="task.status === 'failed'" style="margin-top: 12px; padding: 12px; background: #f8d7da; border-radius: 6px; color: #721c24;">
          ❌ {{ task.error || '导出失败' }}
        </div>
        
        <!-- 操作按钮 -->
        <div class="task-actions">
          <button 
            v-if="task.status === 'running' || task.status === 'extracting'" 
            @click="pauseTask(task.id)"
            class="btn btn-warning btn-sm"
          >
            ⏸ 暂停
          </button>
          <button 
            v-if="task.status === 'paused'" 
            @click="resumeTask(task.id)"
            class="btn btn-success btn-sm"
          >
            ▶ 恢复
          </button>
          <button 
            v-if="['extracting', 'running', 'paused'].includes(task.status)" 
            @click="cancelTask(task.id)"
            class="btn btn-danger btn-sm"
          >
            ✖ 取消
          </button>
          <button 
            v-if="task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled'"
            @click="deleteTask(task.id)"
            class="btn btn-outline btn-sm"
          >
            🗑 删除
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

const loading = ref(true)
const tasks = ref([])
const expandedDetailed = ref({})
const parsedChatIds = ref([])
const parsedMessageIds = ref([])
const refreshInterval = ref(3000)
let intervalId = null

function isDetailedExpanded(task) {
  // 如果用户手动点击过，按用户的选择来
  if (expandedDetailed.value[task.id] !== undefined) {
    return expandedDetailed.value[task.id]
  }
  // 运行中或暂停的任务默认展示详情
  return ['running', 'paused', 'extracting'].includes(task.status)
}

// 统计
const completedCount = computed(() => tasks.value.filter(t => t.status === 'completed').length)
const pendingCount = computed(() => tasks.value.filter(t => ['extracting', 'pending', 'running', 'paused'].includes(t.status)).length)
const failedCount = computed(() => tasks.value.filter(t => t.status === 'failed').length)
const runningCount = computed(() => tasks.value.filter(t => ['extracting', 'running'].includes(t.status)).length)
const pausedCount = computed(() => tasks.value.filter(t => t.status === 'paused').length)

function getAuthHeader() {
  return { Authorization: `Bearer ${localStorage.getItem('token')}` }
}

function getProgress(task) {
  if (task.total_messages === 0) return 0
  return (task.processed_messages / task.total_messages) * 100
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

async function pauseTask(taskId) {
  try {
    await axios.post(`/api/export/${taskId}/pause`, {}, { headers: getAuthHeader() })
    await fetchTasks()
  } catch (err) {
    alert('暂停失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function resumeTask(taskId) {
  try {
    await axios.post(`/api/export/${taskId}/resume`, {}, { headers: getAuthHeader() })
    await fetchTasks()
  } catch (err) {
    alert('恢复失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function cancelTask(taskId) {
  try {
    await axios.post(`/api/export/${taskId}/cancel`, {}, { headers: getAuthHeader() })
    await fetchTasks()
  } catch (err) {
    alert('取消失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function retryFailed(taskId) {
  try {
    const res = await axios.post(`/api/export/${taskId}/retry`, {}, { headers: getAuthHeader() })
    alert(res.data.message)
  } catch (err) {
    alert('重试失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function deleteTask(taskId) {
  if (!confirm('确定要删除此任务吗？')) return
  try {
    await axios.delete(`/api/export/${taskId}`, { headers: getAuthHeader() })
    tasks.value = tasks.value.filter(t => t.id !== taskId)
  } catch (err) {
    alert('删除失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function pauseAll() {
  for (const task of tasks.value.filter(t => ['extracting', 'running'].includes(t.status))) {
    await pauseTask(task.id)
  }
}

async function resumeAll() {
  for (const task of tasks.value.filter(t => t.status === 'paused')) {
    await resumeTask(task.id)
  }
}

async function removeCompleted() {
  if (!confirm('确定要移除所有已完成的任务吗？')) return
  for (const task of tasks.value.filter(t => t.status === 'completed')) {
    await deleteTask(task.id)
  }
}

function toggleDetailed(taskId) {
  expandedDetailed.value[taskId] = !expandedDetailed.value[taskId]
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN')
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

onMounted(() => {
  fetchTasks()
  // 每 3 秒刷新一次运行中的任务
  intervalId = setInterval(() => {
    if (tasks.value.some(t => ['extracting', 'running', 'paused'].includes(t.status))) {
      fetchTasks()
    }
  }, refreshInterval.value)
})

onUnmounted(() => {
  if (intervalId) {
    clearInterval(intervalId)
  }
})
</script>

<style scoped>
.download-item-row {
  display: flex;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid rgba(0,0,0,0.05);
}
.download-item-row:last-child {
  border-bottom: none;
}
.item-status {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  text-transform: uppercase;
  font-weight: 600;
}
.item-status.waiting { background: #eee; color: #666; }
.item-status.downloading { background: #e3f2fd; color: #1976d2; }
.item-status.completed { background: #e8f5e9; color: #2e7d32; }
.item-status.failed { background: #ffebee; color: #c62828; }
.item-status.paused { background: #fff3e0; color: #ef6c00; }
.item-status.skipped { background: #f5f5f5; color: #9e9e9e; }

.status-badge.status-extracting {
  background: #f3e5f5;
  color: #7b1fa2;
}

.completed-info-box {
  margin-top: 12px;
  padding: 10px 15px;
  background: #fafffb;
  border: 1px solid #e7f5ed;
  border-left: 4px solid #27ae60;
  border-radius: 4px;
}
</style>
