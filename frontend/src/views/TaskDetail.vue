<template>
  <div class="fade-in">
    <div class="page-header">
      <div class="header-text">
        <h1 class="task-title-main">📊 {{ task.name || '加载中...' }}</h1>
        <p class="subtitle">实时监控下载进度与文件状态</p>
      </div>
      <div class="header-actions">
        <div class="global-stats-pill">
          <span class="speed-value">{{ formatSpeed(task.download_speed) }}</span>
          <span class="speed-label">总速度</span>
        </div>
      </div>
    </div>

    <!-- 顶部操作栏 (增强手机端适配) -->
    <div class="premium-card actions-panel">
      <div class="progress-info">
        <div class="p-main">
          <span class="p-percent">{{ (task.progress || 0).toFixed(1) }}%</span>
          <span class="p-count">{{ task.downloaded_media }} / {{ task.total_media }} 文件</span>
        </div>
        <div class="p-bar-container">
          <div class="p-bar-fill" :class="task.status" :style="{ width: (task.progress || 0) + '%' }"></div>
        </div>
      </div>
      
      <div class="button-group">
        <button v-if="['running', 'extracting'].includes(task.status)" @click="pauseTask" class="btn-premium warning sm">⏸ 暂停所有</button>
        <button v-if="task.status === 'paused'" @click="resumeTask" class="btn-premium success sm">▶ 恢复所有</button>
        <button @click="verifyIntegrity" class="btn-premium info sm">📊 批量校验</button>
        <button @click="cancelTask" class="btn-premium danger sm">✖ 取消导出</button>
        <button @click="deleteTask" class="btn-premium ghost-danger sm">🗑 删除任务</button>
      </div>
    </div>

    <!-- 顶部统计卡片 (作为过滤器) -->
    <div class="summary-grid">
      <div class="stat-card clickable pointer" :class="{ active: currentTab === 'active' }" @click="currentTab = 'active'">
        <div class="stat-icon">⚡</div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.active || 0 }}</div>
          <div class="stat-label">正在下载/暂停</div>
        </div>
      </div>
      <div class="stat-card pointer" :class="{ active: currentTab === 'waiting' }" @click="currentTab = 'waiting'">
        <div class="stat-icon">⏳</div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.waiting || 0 }}</div>
          <div class="stat-label">等待队列</div>
        </div>
      </div>
      <div class="stat-card pointer" :class="{ active: currentTab === 'failed' }" @click="currentTab = 'failed'">
        <div class="stat-icon">❌</div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.failed || 0 }}</div>
          <div class="stat-label">下载失败</div>
        </div>
      </div>
      <div class="stat-card pointer" :class="{ active: currentTab === 'completed' }" @click="currentTab = 'completed'">
        <div class="stat-icon">✅</div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.completed || 0 }}</div>
          <div class="stat-label">已完成/跳过</div>
        </div>
      </div>
    </div>

    <!-- 统一任务列表 -->
    <div class="unified-task-list">
      <div class="list-toolbar">
        <div class="filter-tabs-wrapper">
          <div class="filter-tabs">
            <button class="tab-btn" :class="{ active: currentTab === 'active' }" @click="currentTab = 'active'">
              活动中 <span class="tab-sub" v-if="currentTab === 'active' && stats.current_concurrency">(并发: {{stats.current_concurrency}}, 线程: {{stats.active_threads}})</span>
            </button>
            <button class="tab-btn" :class="{ active: currentTab === 'waiting' }" @click="currentTab = 'waiting'">等待中</button>
            <button class="tab-btn" :class="{ active: currentTab === 'failed' }" @click="currentTab = 'failed'">已失败</button>
            <button class="tab-btn" :class="{ active: currentTab === 'completed' }" @click="currentTab = 'completed'">已完成</button>
          </div>
        </div>
        <div class="header-right-tools">
          <button @click="toggleSort" class="btn-premium ghost sm sort-btn" :title="reversedOrder ? '当前为倒序' : '当前为正序'">
            {{ reversedOrder ? '⇅ 倒序' : '⇅ 正序' }}
          </button>
          <div class="v-divider"></div>
          <button @click="toggleViewAll" class="btn-premium ghost sm">{{ viewAll ? '显示精简' : '查看全部' }}</button>
        </div>
      </div>

      <div class="queue-list" style="max-height: 60vh;">
        <div v-for="item in filteredList" :key="item.id" class="queue-item" :class="item.status">
          <div class="item-main">
            <div class="item-name" :title="item.file_name">
              <span class="file-type-icon">{{ getFileIcon(item.media_type) }}</span>
              {{ item.file_name }}
            </div>
            <div class="item-meta">
              <span class="file-size">
                <span v-if="['completed', 'failed', 'paused'].includes(item.status) && item.downloaded_size > 0" class="actual-size">本地: {{ formatSize(item.downloaded_size) }} / </span>
                云端: {{ formatSize(item.file_size) }}
              </span>
              <span v-if="item.status === 'downloading'" class="item-speed">{{ formatSpeed(item.speed) }}</span>
              <span class="item-percent" v-if="item.status === 'downloading' || (item.progress > 0 && item.progress < 100)">{{ item.progress.toFixed(1) }}%</span>
              <span class="item-status-text" :class="item.status">{{ getStatusLabel(item.status) }}</span>
            </div>
            <div class="item-progress" v-if="item.status === 'downloading' || (item.progress > 0 && item.progress < 100)">
              <div class="progress-tiny">
                <div class="fill" :style="{ width: item.progress + '%' }"></div>
              </div>
            </div>
          </div>
          <div class="item-actions">
            <!-- 活动/暂停项目：重试 -->
            <button v-if="['downloading', 'paused', 'waiting'].includes(item.status)" @click="retryItem(item.id)" class="action-btn-circle" title="重新下载此文件">🔄</button>
            
            <!-- 正在下载或等待中：暂停 (释放槽位) 或 挂起 (驻留槽位) -->
            <button v-if="['downloading', 'waiting'].includes(item.status)" @click="pauseItem(item.id)" class="action-btn-circle warning" title="暂停 (释放槽位，Worker 去下载其他文件)">⏸</button>
            <button v-if="['downloading', 'waiting'].includes(item.status)" @click="suspendItem(item.id)" class="action-btn-circle" title="挂起 (驻留槽位，降低总并发)" style="background: #6c5ce7; color: white;">⏼</button>
            <!-- 已暂停/挂起：恢复 -->
            <button v-if="item.status === 'paused'" @click="resumeItem(item.id)" class="action-btn-circle success" title="恢复">▶</button>
            
            <!-- 失败或已完成：重试 -->
            <button v-if="['failed', 'completed', 'skipped'].includes(item.status)" @click="retryItem(item.id)" class="action-btn-circle" title="重试/重新下载">🔄</button>
            
            <!-- 通用：取消/跳过 -->
            <button @click="cancelItem(item.id)" class="action-btn-circle danger" title="取消/跳过">✖</button>
          </div>
        </div>
        <div v-if="filteredList.length === 0" class="empty-mini">
          {{ getEmptyText() }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id

const task = ref({})
const queue = ref({ downloading: [], waiting: [], failed: [], completed: [] })
const stats = ref({
  active: 0,
  waiting: 0,
  failed: 0,
  completed: 0,
  current_concurrency: 0,
  active_threads: 0
})
const currentTab = ref('active')
const viewAll = ref(false)
const reversedOrder = ref(false)
let refreshTimer = null

function getAuthHeader() {
  return { Authorization: `Bearer ${localStorage.getItem('token')}` }
}

const filteredList = computed(() => {
  if (currentTab.value === 'active') return queue.value.downloading
  if (currentTab.value === 'waiting') return queue.value.waiting
  if (currentTab.value === 'failed') return queue.value.failed
  if (currentTab.value === 'completed') return queue.value.completed
  return []
})

async function fetchData() {
  try {
    const currentLimit = viewAll.value ? 0 : 50
    
    const [taskRes, queueRes] = await Promise.all([
      axios.get(`/api/export/${taskId}`, { headers: getAuthHeader() }),
      axios.get(`/api/export/${taskId}/downloads`, { 
        params: { 
          limit: currentLimit,
          reversed_order: reversedOrder.value
        }, 
        headers: getAuthHeader() 
      })
    ])
    
    task.value = taskRes.data
    const newData = queueRes.data
    
    queue.value.downloading = newData.downloading
    queue.value.waiting = newData.waiting
    queue.value.failed = newData.failed || []
    queue.value.completed = newData.completed
    stats.value = {
      ...newData.counts,
      current_concurrency: newData.current_concurrency,
      active_threads: newData.active_threads
    }
  } catch (err) {
    console.error('获取详情失败:', err)
    if (err.response?.status === 404) {
      router.push('/tasks')
    }
  }
}

function toggleViewAll() {
  viewAll.value = !viewAll.value
  fetchData()
}

function toggleSort() {
  reversedOrder.value = !reversedOrder.value
  fetchData()
}

function getFileIcon(type) {
  const icons = {
    photo: '🖼️',
    video: '🎬',
    audio: '🎵',
    voice: '🎤',
    video_note: '📹',
    document: '📄',
    sticker: '🏷️',
    animation: '🎡'
  }
  return icons[type] || '📁'
}

function getEmptyText() {
  const texts = {
    active: '暂无活跃下载或暂停的任务',
    waiting: '队列中没有等待中的文件',
    failed: '没有任何下载失败的记录',
    completed: '还没有已完成或跳过的文件'
  }
  return texts[currentTab.value] || '暂无内容'
}

// 任务操作
async function pauseTask() { await axios.post(`/api/export/${taskId}/pause`, {}, { headers: getAuthHeader() }); fetchData() }
async function resumeTask() { await axios.post(`/api/export/${taskId}/resume`, {}, { headers: getAuthHeader() }); fetchData() }
async function cancelTask() { if(confirm('确定取消整个导出任务？')) { await axios.post(`/api/export/${taskId}/cancel`, {}, { headers: getAuthHeader() }); router.push('/tasks') } }
async function deleteTask() { if(confirm('确定彻底删除该任务？')) { await axios.delete(`/api/export/${taskId}`, { headers: getAuthHeader() }); router.push('/tasks') } }

// 单文件操作
async function pauseItem(itemId) { await axios.post(`/api/export/${taskId}/download/${itemId}/pause`, {}, { headers: getAuthHeader() }); fetchData() }
async function suspendItem(itemId) { await axios.post(`/api/export/${taskId}/download/${itemId}/suspend`, {}, { headers: getAuthHeader() }); fetchData() }
async function resumeItem(itemId) { await axios.post(`/api/export/${taskId}/download/${itemId}/resume`, {}, { headers: getAuthHeader() }); fetchData() }
async function cancelItem(itemId) { if(confirm('确定跳过此文件下载？')) { await axios.post(`/api/export/${taskId}/download/${itemId}/cancel`, {}, { headers: getAuthHeader() }); fetchData() } }
async function retryItem(itemId) { await axios.post(`/api/export/${taskId}/retry_file/${itemId}`, {}, { headers: getAuthHeader() }); fetchData() }
async function verifyIntegrity() {
  try {
    const res = await axios.post(`/api/export/${taskId}/verify`, {}, { headers: getAuthHeader() })
    alert(res.data.message)
    fetchData()
  } catch (err) {
    alert('校验失败: ' + (err.response?.data?.detail || err.message))
  }
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return (bytes / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i]
}

function formatSpeed(bps) {
  if (!bps || bps < 0) return '0 B/s'
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
  let i = 0
  while (bps >= 1024 && i < units.length - 1) { bps /= 1024; i++ }
  return bps.toFixed(1) + ' ' + units[i]
}

function getStatusLabel(status) {
  const labels = {
    waiting: '等待',
    downloading: '下载中',
    paused: '已暂停',
    completed: '完成',
    failed: '失败',
    skipped: '已跳过'
  }
  return labels[status] || status
}

onMounted(() => {
  fetchData()
  refreshTimer = setInterval(fetchData, 2000)
})

onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })
</script>

<style scoped>
.task-title-main { font-size: 1.75rem; font-weight: 800; color: #18181b; }
.header-actions { display: flex; align-items: center; }

.global-stats-pill {
  background: #eff6ff;
  padding: 8px 20px;
  border-radius: 50px;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  border: 1px solid #dbeafe;
}
.speed-value { font-size: 1.25rem; font-weight: 800; color: #1e40af; line-height: 1; }
.speed-label { font-size: 0.7rem; color: #60a5fa; font-weight: 700; text-transform: uppercase; margin-top: 2px; }

.actions-panel {
  padding: 24px;
  margin-bottom: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 40px;
}

.progress-info { flex: 1; }
.p-main { display: flex; align-items: baseline; gap: 12px; margin-bottom: 8px; }
.p-percent { font-size: 1.5rem; font-weight: 800; color: #18181b; }
.p-count { font-size: 0.85rem; color: #71717a; font-weight: 600; }
.p-bar-container { height: 12px; background: #f4f4f5; border-radius: 6px; overflow: hidden; }
.p-bar-fill { height: 100%; transition: width 0.5s ease; background: #3b82f6; }
.p-bar-fill.completed { background: #22c55e; }
.p-bar-fill.paused { background: #f59e0b; }

.button-group { display: flex; gap: 12px; flex-shrink: 0; }

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 24px;
}

/* 复用 style.css 中定义的 stat-card，但在这里添加 active 状态 */
.stat-card.pointer { cursor: pointer; transition: all 0.2s; border: 1px solid #f4f4f5; }
.stat-card.pointer:hover { transform: translateY(-2px); border-color: #3b82f6; }
.stat-card.pointer.active { border-color: #3b82f6; background: #eff6ff; }

.unified-task-list {
  background: white;
  border-radius: 20px;
  border: 1px solid #f4f4f5;
  box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05);
}

.list-toolbar {
  padding: 16px 20px;
  border-bottom: 1px solid #f4f4f5;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.sort-btn {
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 6px;
  border: 1px solid #e4e4e7;
  margin-right: 8px;
}
.sort-btn:hover { border-color: #3b82f6; color: #3b82f6; }

.v-divider { width: 1px; height: 20px; background: #e4e4e7; margin: 0 12px; }

.filter-tabs-wrapper {
  background: #f4f4f5;
  padding: 4px;
  border-radius: 12px;
  display: inline-flex;
}

.filter-tabs {
  display: flex;
  gap: 2px;
}

.tab-btn {
  padding: 8px 16px;
  border-radius: 9px;
  border: none;
  background: transparent;
  font-size: 0.9rem;
  font-weight: 500;
  color: #71717a;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.tab-btn:hover:not(.active) { color: #18181b; }

.tab-btn.active {
  background: white;
  color: #18181b;
  box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1);
}

.tab-sub {
  font-size: 0.7rem;
  opacity: 0.6;
  font-weight: 400;
  margin-top: -2px;
}

.queue-list { padding: 10px; overflow-y: auto; }
.empty-mini { padding: 60px; text-align: center; color: #a1a1aa; font-size: 0.9rem; }

.queue-item {
  display: flex;
  padding: 16px;
  background: #fafafa;
  border-radius: 16px;
  margin-bottom: 12px;
  gap: 16px;
  border: 1px solid transparent;
  transition: 0.2s;
}
.queue-item:hover { background: white; border-color: #3b82f6; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }

.item-main { flex: 1; min-width: 0; }
.item-name { 
  font-size: 0.9rem; font-weight: 700; color: #18181b; 
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; 
  margin-bottom: 6px; display: flex; align-items: center; gap: 8px;
}
.file-type-icon { font-size: 1.1rem; }

.item-meta { display: flex; align-items: center; gap: 12px; font-size: 0.75rem; color: #71717a; font-weight: 600; }
.item-speed { color: #3b82f6; }
.item-percent { color: #8b5cf6; }

.item-status-text { 
  font-size: 0.65rem; padding: 2px 8px; border-radius: 6px; 
  background: #f4f4f5; text-transform: uppercase; margin-left: auto;
}
.item-status-text.downloading { background: #dbeafe; color: #1e40af; }
.item-status-text.completed { background: #dcfce7; color: #166534; }
.item-status-text.paused { background: #fef3c7; color: #92400e; }
.item-status-text.failed { background: #fee2e2; color: #991b1b; }

.item-progress { margin-top: 10px; }
.progress-tiny { height: 6px; background: #f4f4f5; border-radius: 3px; overflow: hidden; }
.progress-tiny .fill { height: 100%; background: #3b82f6; transition: width 0.3s; }

.item-actions { display: flex; align-items: center; gap: 8px; }

.action-btn-circle {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid #e4e4e7;
  background: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
  color: #71717a;
}

.action-btn-circle:hover {
  background: #f4f4f5;
  border-color: #3b82f6;
  color: #3b82f6;
  transform: scale(1.1);
}

.action-btn-circle.warning:hover { border-color: #f59e0b; color: #f59e0b; background: #fffbeb; }
.action-btn-circle.success:hover { border-color: #22c55e; color: #22c55e; background: #f0fdf4; }
.action-btn-circle.danger:hover { border-color: #ef4444; color: #ef4444; background: #fef2f2; }

@media (max-width: 640px) {
  .actions-panel { flex-direction: column; align-items: stretch; gap: 20px; }
  .summary-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
  .queue-item { flex-direction: column; gap: 12px; }
  .item-actions { justify-content: flex-end; border-top: 1px dashed #f4f4f5; padding-top: 10px; }
  .list-toolbar { flex-direction: column; align-items: stretch; gap: 12px; }
  .filter-tabs { overflow-x: auto; }
}
</style>
