<template>
  <div class="fade-in">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
      <h1>📋 任务管理</h1>
      <router-link to="/export" class="btn btn-primary">+ 新建导出</router-link>
    </div>
    
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
    </div>
    
    <div v-else-if="tasks.length === 0" class="card" style="text-align: center; padding: 40px;">
      <div style="font-size: 48px; margin-bottom: 15px;">📭</div>
      <p style="color: #666;">暂无导出任务</p>
      <router-link to="/export" class="btn btn-primary" style="margin-top: 15px;">创建第一个任务</router-link>
    </div>
    
    <div v-else>
      <div v-for="task in tasks" :key="task.id" class="card" style="margin-bottom: 15px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
          <div>
            <h3 style="margin-bottom: 5px;">{{ task.name }}</h3>
            <div style="color: #666; font-size: 14px;">
              创建于 {{ formatDate(task.created_at) }}
            </div>
          </div>
          <span :class="'status-badge status-' + task.status">
            {{ statusText[task.status] }}
          </span>
        </div>
        
        <!-- 进度条 -->
        <div v-if="task.status === 'running'" style="margin-top: 15px;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
            <span>进度</span>
            <span>{{ task.progress.toFixed(1) }}%</span>
          </div>
          <div class="progress">
            <div class="progress-bar" :style="{ width: task.progress + '%' }"></div>
          </div>
          <div style="display: flex; justify-content: space-between; margin-top: 10px; color: #666; font-size: 13px;">
            <span>消息: {{ task.processed_messages }}/{{ task.total_messages }}</span>
            <span>媒体: {{ task.downloaded_media }}/{{ task.total_media }}</span>
            <span>大小: {{ formatSize(task.downloaded_size) }}</span>
          </div>
        </div>
        
        <!-- 完成信息 -->
        <div v-if="task.status === 'completed'" style="margin-top: 15px; padding: 15px; background: #d4edda; border-radius: 8px;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
              <div>✅ 导出完成</div>
              <div style="font-size: 13px; color: #666;">
                {{ task.processed_messages }} 条消息, {{ task.downloaded_media }} 个媒体文件
              </div>
            </div>
            <a :href="'/exports/' + task.id" target="_blank" class="btn btn-success">
              📁 查看文件
            </a>
          </div>
        </div>
        
        <!-- 错误信息 -->
        <div v-if="task.status === 'failed'" style="margin-top: 15px; padding: 15px; background: #f8d7da; border-radius: 8px; color: #721c24;">
          ❌ {{ task.error || '导出失败' }}
        </div>
        
        <!-- 操作按钮 -->
        <div style="margin-top: 15px; display: flex; gap: 10px;">
          <button 
            v-if="task.status === 'running'" 
            @click="cancelTask(task.id)"
            class="btn btn-danger"
          >
            取消
          </button>
          <button 
            v-if="task.status === 'completed' || task.status === 'failed'"
            @click="deleteTask(task.id)"
            class="btn btn-outline"
          >
            删除
          </button>
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
let refreshInterval = null

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

async function cancelTask(taskId) {
  try {
    await axios.post(`/api/export/${taskId}/cancel`, {}, { headers: getAuthHeader() })
    await fetchTasks()
  } catch (err) {
    alert('取消失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function deleteTask(taskId) {
  if (!confirm('确定要删除此任务吗？')) return
  // 这里可以添加删除 API
  tasks.value = tasks.value.filter(t => t.id !== taskId)
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
  refreshInterval = setInterval(() => {
    if (tasks.value.some(t => t.status === 'running')) {
      fetchTasks()
    }
  }, 3000)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>
