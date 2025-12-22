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

    <!-- 顶部操作栏 -->
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
        <button @click="cancelTask" class="btn-premium danger sm">✖ 取消导出</button>
        <button @click="deleteTask" class="btn-premium ghost-danger sm">🗑 删除任务</button>
      </div>
    </div>

    <!-- 三段式任务列表 -->
    <div class="monitoring-grid">
      <!-- 下载中 -->
      <div class="monitor-column">
        <div class="column-header">
          <span class="c-title">⚡ 正在下载</span>
          <span class="c-badge info">{{ queue.downloading?.length || 0 }}</span>
        </div>
        <div class="queue-list">
          <div v-for="item in queue.downloading" :key="item.id" class="queue-item downloading">
            <div class="item-main">
              <div class="item-name" :title="item.file_name">{{ item.file_name }}</div>
              <div class="item-meta">
                <span>{{ formatSize(item.file_size) }}</span>
                <span class="item-speed" v-if="item.speed > 0">{{ formatSpeed(item.speed) }}</span>
              </div>
              <div class="item-progress">
                <div class="progress-tiny">
                  <div class="fill" :style="{ width: item.progress + '%' }"></div>
                </div>
              </div>
            </div>
            <div class="item-actions">
              <button @click="cancelItem(item.id)" class="action-btn" title="跳过此文件">✖</button>
            </div>
          </div>
          <div v-if="!queue.downloading || queue.downloading.length === 0" class="empty-mini">无活跃下载</div>
        </div>
      </div>

      <!-- 等待中 -->
      <div class="monitor-column">
        <div class="column-header">
          <span class="c-title">⏳ 等待队列</span>
          <span class="c-badge warning">{{ queue.waiting?.length || 0 }}</span>
        </div>
        <div class="queue-list">
          <div v-for="item in queue.waiting" :key="item.id" class="queue-item">
            <div class="item-main">
              <div class="item-name" :title="item.file_name">{{ item.file_name }}</div>
              <div class="item-meta">
                <span>{{ formatSize(item.file_size) }}</span>
                <span class="item-status-text" :class="item.status">{{ getStatusLabel(item.status) }}</span>
              </div>
            </div>
            <div class="item-actions">
              <button v-if="item.status === 'paused'" @click="resumeItem(item.id)" class="action-btn" title="恢复">▶</button>
              <button v-else @click="pauseItem(item.id)" class="action-btn" title="暂停">⏸</button>
              <button @click="cancelItem(item.id)" class="action-btn danger" title="跳过">✖</button>
            </div>
          </div>
          <div v-if="!queue.waiting || queue.waiting.length === 0" class="empty-mini">队列已空</div>
        </div>
      </div>

      <!-- 已完成/跳过 -->
      <div class="monitor-column">
        <div class="column-header">
          <span class="c-title">✅ 最近完成</span>
          <span class="c-badge success">{{ queue.completed?.length || 0 }}</span>
        </div>
        <div class="queue-list">
          <div v-for="item in queue.completed" :key="item.id" class="queue-item completed">
            <div class="item-main">
              <div class="item-name" :title="item.file_name">{{ item.file_name }}</div>
              <div class="item-meta">
                <span>{{ formatSize(item.file_size) }}</span>
                <span class="item-status-text" :class="item.status">{{ getStatusLabel(item.status) }}</span>
              </div>
            </div>
            <div class="item-actions">
              <button @click="retryItem(item.id)" class="action-btn" title="重新下载">🔄</button>
            </div>
          </div>
          <div v-if="!queue.completed || queue.completed.length === 0" class="empty-mini">暂无记录</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id

const task = ref({})
const queue = ref({ downloading: [], waiting: [], completed: [] })
let refreshTimer = null

function getAuthHeader() {
  return { Authorization: `Bearer ${localStorage.getItem('token')}` }
}

async function fetchData() {
  try {
    const [taskRes, queueRes] = await Promise.all([
      axios.get(`/api/export/${taskId}`, { headers: getAuthHeader() }),
      axios.get(`/api/export/${taskId}/downloads?limit=20`, { headers: getAuthHeader() })
    ])
    task.value = taskRes.data
    queue.value = queueRes.data
  } catch (err) {
    console.error('获取详情失败:', err)
    if (err.response?.status === 404) {
      router.push('/tasks')
    }
  }
}

// 任务操作
async function pauseTask() { await axios.post(`/api/export/${taskId}/pause`, {}, { headers: getAuthHeader() }); fetchData() }
async function resumeTask() { await axios.post(`/api/export/${taskId}/resume`, {}, { headers: getAuthHeader() }); fetchData() }
async function cancelTask() { if(confirm('确定取消整个导出任务？')) { await axios.post(`/api/export/${taskId}/cancel`, {}, { headers: getAuthHeader() }); router.push('/tasks') } }
async function deleteTask() { if(confirm('确定彻底删除该任务？')) { await axios.delete(`/api/export/${taskId}`, { headers: getAuthHeader() }); router.push('/tasks') } }

// 单文件操作
async function pauseItem(itemId) { await axios.post(`/api/export/${taskId}/download/${itemId}/pause`, {}, { headers: getAuthHeader() }); fetchData() }
async function resumeItem(itemId) { await axios.post(`/api/export/${taskId}/download/${itemId}/resume`, {}, { headers: getAuthHeader() }); fetchData() }
async function cancelItem(itemId) { if(confirm('确定跳过此文件下载？')) { await axios.post(`/api/export/${taskId}/download/${itemId}/cancel`, {}, { headers: getAuthHeader() }); fetchData() } }
async function retryItem(itemId) { await axios.post(`/api/export/${taskId}/retry_file/${itemId}`, {}, { headers: getAuthHeader() }); fetchData() }

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++ }
  return bytes.toFixed(1) + ' ' + units[i]
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
    downloading: '正在下载',
    paused: '已暂停',
    completed: '完成',
    failed: '失败',
    skipped: '已跳过'
  }
  return labels[status] || status
}

onMounted(() => {
  fetchData()
  refreshTimer = setInterval(fetchData, 2000) // 详情页刷新快一点 (2s)
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

.monitoring-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  align-items: start;
}

@media (max-width: 1000px) {
  .monitoring-grid { grid-template-columns: 1fr; }
}

.monitor-column {
  background: white;
  border-radius: 20px;
  border: 1px solid #f4f4f5;
  box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05);
  display: flex;
  flex-direction: column;
  max-height: 80vh;
}

.column-header {
  padding: 16px 20px;
  border-bottom: 1px solid #f4f4f5;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.c-title { font-weight: 800; color: #18181b; font-size: 1rem; }
.c-badge {
  font-size: 0.7rem; font-weight: 800; padding: 4px 10px; border-radius: 50px;
}
.c-badge.info { background: #dbeafe; color: #1e40af; }
.c-badge.warning { background: #fef3c7; color: #92400e; }
.c-badge.success { background: #dcfce7; color: #166534; }

.queue-list { padding: 10px; overflow-y: auto; flex: 1; }
.empty-mini { padding: 40px; text-align: center; color: #a1a1aa; font-size: 0.9rem; }

.queue-item {
  display: flex;
  padding: 12px;
  background: #fafafa;
  border-radius: 12px;
  margin-bottom: 10px;
  gap: 12px;
  border: 1px solid transparent;
  transition: 0.2s;
}
.queue-item:hover { transform: scale(1.02); background: white; border-color: #f4f4f5; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05); }

.item-main { flex: 1; min-width: 0; }
.item-name { font-size: 0.8rem; font-weight: 700; color: #3f3f46; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px; }
.item-meta { display: flex; justify-content: space-between; font-size: 0.7rem; color: #a1a1aa; font-weight: 600; }
.item-speed { color: #3b82f6; }
.item-status-text { font-size: 0.65rem; padding: 2px 6px; border-radius: 4px; background: #f4f4f5; text-transform: uppercase; }
.item-status-text.completed { background: #dcfce7; color: #166534; }
.item-status-text.skipped { background: #f4f4f5; color: #71717a; }
.item-status-text.failed { background: #fee2e2; color: #991b1b; }

.item-progress { margin-top: 6px; }
.progress-tiny { height: 4px; background: #f4f4f5; border-radius: 2px; overflow: hidden; }
.progress-tiny .fill { height: 100%; background: #3b82f6; transition: width 0.3s; }

.item-actions { display: flex; align-items: center; gap: 4px; }
.action-btn {
  width: 28px; height: 28px; border-radius: 8px; border: none; background: white;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  font-size: 0.8rem; border: 1px solid #f4f4f5; transition: 0.2s;
}
.action-btn:hover { background: #f4f4f5; transform: translateY(-2px); }
.action-btn.danger { color: #ef4444; }

/* Premium Buttons */
.btn-premium {
  padding: 10px 20px; border-radius: 12px; font-weight: 700; border: none; cursor: pointer; transition: 0.2s;
}
.btn-premium.sm { padding: 8px 16px; font-size: 0.85rem; }
.btn-premium.success { background: #22c55e; color: white; }
.btn-premium.warning { background: #f59e0b; color: white; }
.btn-premium.danger { background: #ef4444; color: white; }
.btn-premium.ghost-danger { background: transparent; border: 2px solid #fee2e2; color: #ef4444; }
.btn-premium:hover { filter: brightness(1.1); transform: translateY(-2px); }
</style>
