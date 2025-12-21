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
          <div class="stat-label">未完成</div>
        </div>
      </div>
      <div class="stat-card failed">
        <div class="stat-icon">❌</div>
        <div class="stat-info">
          <div class="stat-value">{{ failedCount }}</div>
          <div class="stat-label">失败</div>
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
      <span class="refresh-label">刷新间隔: {{ refreshInterval / 1000 }}s</span>
    </div>
    
    <!-- 加载中 -->
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
    </div>
    
    <!-- 空状态 -->
    <div v-else-if="tasks.length === 0" class="empty-state">
      <div class="icon">📭</div>
      <p>暂无导出任务</p>
      <router-link to="/export" class="btn btn-primary">创建第一个任务</router-link>
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
          <span :class="'status-badge status-' + task.status">
            {{ statusText[task.status] }}
          </span>
        </div>
        
        <!-- 进度条 (运行中) -->
        <div v-if="task.status === 'running' || task.status === 'paused'">
          <div class="progress">
            <div class="progress-bar" :style="{ width: getProgress(task) + '%' }"></div>
          </div>
          <div class="progress-text">
            <span>{{ getProgress(task).toFixed(1) }}%</span>
            <span>{{ task.processed_messages }}/{{ task.total_messages }} 消息</span>
          </div>
        </div>
        
        <!-- 任务信息 -->
        <div class="task-info">
          <div class="task-info-item">
            📨 消息: {{ task.processed_messages }}/{{ task.total_messages }}
          </div>
          <div class="task-info-item">
            📁 媒体: {{ task.downloaded_media }}/{{ task.total_media }}
          </div>
          <div class="task-info-item">
            💾 大小: {{ formatSize(task.downloaded_size) }}
          </div>
          <div class="task-info-item" v-if="task.failed_downloads?.length > 0">
            ⚠️ 失败: {{ task.failed_downloads.length }}
          </div>
        </div>
        
        <!-- 失败下载区域 -->
        <div v-if="task.failed_downloads?.length > 0" class="failed-section">
          <div class="failed-header" @click="toggleFailed(task.id)">
            <span>⚠️ {{ task.failed_downloads.length }} 个下载失败</span>
            <span>{{ expandedTasks[task.id] ? '▼' : '▶' }}</span>
          </div>
          <div v-if="expandedTasks[task.id]" class="failed-list">
            <div v-for="fail in task.failed_downloads.slice(0, 5)" :key="fail.message_id" class="failed-item">
              <span>{{ fail.file_name || `消息 #${fail.message_id}` }}</span>
              <span class="error-type">{{ fail.error_type }}</span>
            </div>
            <div v-if="task.failed_downloads.length > 5" class="failed-item">
              还有 {{ task.failed_downloads.length - 5 }} 个...
            </div>
          </div>
        </div>
        
        <!-- 完成信息 -->
        <div v-if="task.status === 'completed'" style="margin-top: 12px; padding: 12px; background: #d4edda; border-radius: 6px;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
              <div style="color: #155724; font-weight: 500;">✅ 导出完成</div>
              <div style="font-size: 12px; color: #666;">
                {{ task.processed_messages }} 条消息, {{ task.downloaded_media }} 个媒体文件
              </div>
            </div>
            <a :href="'/exports/' + task.id" target="_blank" class="btn btn-success btn-sm">
              📁 查看文件
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
            v-if="task.status === 'running'" 
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
            v-if="task.status === 'running' || task.status === 'paused'" 
            @click="cancelTask(task.id)"
            class="btn btn-danger btn-sm"
          >
            ✖ 取消
          </button>
          <button 
            v-if="task.failed_downloads?.length > 0"
            @click="retryFailed(task.id)"
            class="btn btn-outline btn-sm"
          >
            🔄 重试失败
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
const expandedTasks = ref({})
const refreshInterval = ref(3000)
let intervalId = null

const statusText = {
  pending: '等待中',
  running: '运行中',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消'
}

// 统计
const completedCount = computed(() => tasks.value.filter(t => t.status === 'completed').length)
const pendingCount = computed(() => tasks.value.filter(t => ['pending', 'running', 'paused'].includes(t.status)).length)
const failedCount = computed(() => tasks.value.filter(t => t.status === 'failed').length)
const runningCount = computed(() => tasks.value.filter(t => t.status === 'running').length)
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
  for (const task of tasks.value.filter(t => t.status === 'running')) {
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

function toggleFailed(taskId) {
  expandedTasks.value[taskId] = !expandedTasks.value[taskId]
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
    if (tasks.value.some(t => t.status === 'running' || t.status === 'paused')) {
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
