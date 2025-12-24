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
        
        <!-- 扫描状态显示 (v1.6.4) -->
        <div v-if="task.status === 'extracting' || task.is_verifying" class="scanning-status-mini fade-in">
          <div class="s-spinner"></div>
          <div class="s-info">
            <span class="s-label">{{ task.is_verifying ? '正在校验:' : '正在扫描:' }}</span>
            <span class="s-chat">{{ task.current_scanning_chat || '初始化...' }}</span>
            <span class="s-msg">进度 ID: #{{ task.current_scanning_msg_id || 0 }}</span>
          </div>
        </div>
        <!-- 校验结果显示 (v1.6.4) -->
        <div v-if="task.last_verify_result && !task.is_verifying" class="verify-result-alert fade-in">
          <span class="v-icon">ℹ️</span>
          <span class="v-text">{{ task.last_verify_result }}</span>
        </div>
      </div>
      
      <div class="button-group main-actions">
        <button v-if="['running', 'extracting'].includes(task.status)" @click="pauseTask" class="btn-premium warning sm">⏸ 暂停任务</button>
        <button v-if="task.status === 'paused'" @click="resumeTask" class="btn-premium success sm">▶ 恢复任务</button>
        
        <div class="action-dropdown">
          <button class="btn-premium info sm dropdown-toggle">🔍 扫描消息</button>
          <div class="dropdown-menu">
            <button @click="scanMessages(false)">增量扫描 (推荐)</button>
            <button @click="scanMessages(true)" class="danger-text">全量扫描 (耗时)</button>
          </div>
        </div>

        <button @click="verifyIntegrity" class="btn-premium primary sm" :disabled="task.is_verifying">
          {{ task.is_verifying ? '正在校验...' : '📊 校验文件' }}
        </button>
        
        <button @click="cancelTask" class="btn-premium danger sm">✖ 取消</button>
        <button @click="deleteTask" class="btn-premium ghost-danger sm">🗑 删除</button>
      </div>
    </div>

    <!-- 统一任务列表 (v1.6.7.2 布局优化) -->
    <div class="unified-task-list">
      <div class="list-toolbar">
        <!-- 统一横排工具栏 -->
        <div class="toolbar-row">
          <!-- 左侧：并发控制 -->
          <div class="toolbar-left">
            <span class="toolbar-label">并发</span>
            <div class="mini-stepper">
              <button @click="adjustConcurrency('max', -1)" :disabled="concurrency.max <= 1">-</button>
              <span class="ctrl-val">{{ concurrency.max }}</span>
              <button @click="adjustConcurrency('max', 1)" :disabled="concurrency.max >= 20">+</button>
            </div>
            <label class="toolbar-toggle">
              <input type="checkbox" v-model="concurrency.enableParallel" @change="toggleParallel">
              <span>⚡并行</span>
            </label>
          </div>
          
          <!-- 右侧：状态和功能 -->
          <div class="toolbar-right">
            <span class="toolbar-status" v-if="stats.current_concurrency">
              🚦 {{stats.current_concurrency}} / {{stats.active_threads}}
            </span>
            <label class="toolbar-toggle tdl" :class="{ active: tdlMode }">
              <input type="checkbox" v-model="tdlMode" @change="toggleTDLMode">
              <span>🚀 TDL</span>
            </label>
            <button @click="toggleSort" class="toolbar-btn" :title="reversedOrder ? '倒序' : '正序'">
              {{ reversedOrder ? '⇅ 倒序' : '⇅ 正序' }}
            </button>
            <button @click="toggleViewAll" class="toolbar-btn">{{ viewAll ? '精简' : '全部' }}</button>
          </div>
        </div>
      </div>

      <!-- 队列选择 Tab -->
      <div class="queue-tabs">
        <button 
          :class="{ active: currentTab === 'active' }" 
          @click="currentTab = 'active'"
        >
          活动中 ({{ stats.active }})
        </button>
        <button 
          :class="{ active: currentTab === 'waiting' }" 
          @click="currentTab = 'waiting'"
        >
          等待中 ({{ stats.waiting }})
        </button>
        <button 
          :class="{ active: currentTab === 'failed' }" 
          @click="currentTab = 'failed'"
        >
          失败 ({{ stats.failed }})
        </button>
        <button 
          :class="{ active: currentTab === 'completed' }" 
          @click="currentTab = 'completed'"
        >
          已完成 ({{ stats.completed }})
        </button>
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
const concurrency = ref({ max: 10, enableParallel: false })  // 并发控制状态
const tdlMode = ref(false)  // TDL 下载模式开关
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
    // 同步 TDL 模式状态
    if (task.value.tdl_mode !== undefined) {
      tdlMode.value = task.value.tdl_mode
    }
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

async function fetchConcurrency() {
  try {
    const res = await axios.get(`/api/export/${taskId}/concurrency`, { headers: getAuthHeader() })
    concurrency.value.max = res.data.current_max_concurrent_downloads || res.data.max_concurrent_downloads
    concurrency.value.enableParallel = res.data.enable_parallel_chunk || false
  } catch (err) {
    console.error('获取并发配置失败:', err)
  }
}

async function adjustConcurrency(type, delta) {
  let newValue
  if (type === 'max') newValue = concurrency.value.max + delta
  
  if (type === 'max' && (newValue < 1 || newValue > 20)) return
  concurrency.value.max = newValue
  
  try {
    await axios.post(`/api/export/${taskId}/concurrency`, null, { 
      params: { max_concurrent_downloads: newValue }, 
      headers: getAuthHeader() 
    })
  } catch (err) {
    concurrency.value.max -= delta
    alert('调整失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function toggleParallel() {
  try {
    await axios.post(`/api/export/${taskId}/concurrency`, null, { 
      params: { parallel_chunk_connections: concurrency.value.enableParallel ? 3 : 1 }, // 内部转换: 3表示开启, 1表示关闭
      headers: getAuthHeader() 
    })
  } catch (err) {
    concurrency.value.enableParallel = !concurrency.value.enableParallel
    alert('调整失败: ' + (err.response?.data?.detail || err.message))
  }
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
async function resumeItem(itemId) { await axios.post(`/api/export/${taskId}/download/${itemId}/resume`, {}, { headers: getAuthHeader() }); fetchData() }
async function cancelItem(itemId) { if(confirm('确定跳过此文件下载？')) { await axios.post(`/api/export/${taskId}/download/${itemId}/cancel`, {}, { headers: getAuthHeader() }); fetchData() } }
async function retryItem(itemId) { await axios.post(`/api/export/${taskId}/retry_file/${itemId}`, {}, { headers: getAuthHeader() }); fetchData() }
async function scanMessages(full) {
  try {
    const res = await axios.post(`/api/export/${taskId}/scan`, null, { 
      params: { full },
      headers: getAuthHeader() 
    })
    alert(res.data.message)
    fetchData()
  } catch (err) {
    alert('扫描启动失败: ' + (err.response?.data?.detail || err.message))
  }
}

async function verifyIntegrity() {
  try {
    const res = await axios.post(`/api/export/${taskId}/verify`, {}, { headers: getAuthHeader() })
    alert(res.data.message)
    fetchData()
  } catch (err) {
    alert('校验失败: ' + (err.response?.data?.detail || err.message))
  }
}

// TDL 下载模式切换 (完全接管模式)
async function toggleTDLMode() {
  try {
    // 调用后端 API 保存 TDL 模式状态
    const res = await axios.post(`/api/export/${taskId}/tdl-mode`, null, {
      params: { enabled: tdlMode.value },
      headers: getAuthHeader()
    })
    
    if (res.data.status === 'ok') {
      console.log('TDL 模式:', res.data.message)
      // 提示用户
      if (tdlMode.value) {
        alert(`✅ TDL 模式已开启\n\n现在点击"恢复任务"将使用 TDL 下载器。`)
      }
    } else {
      alert(res.data.message || 'TDL 模式设置失败')
      tdlMode.value = !tdlMode.value  // 恢复原状态
    }
  } catch (err) {
    console.error('TDL 模式切换失败:', err)
    tdlMode.value = !tdlMode.value  // 恢复原状态
    alert('TDL 操作失败: ' + (err.response?.data?.detail || err.message))
  }
}

let tdlProgressTimer = null

function startTDLProgressPolling() {
  if (tdlProgressTimer) return
  
  tdlProgressTimer = setInterval(async () => {
    try {
      const res = await axios.get(`/api/export/${taskId}/tdl-progress`, { 
        headers: getAuthHeader() 
      })
      
      if (res.data && res.data.items) {
        // 更新下载队列中的进度
        for (const tdlItem of res.data.items) {
          const queueItem = findQueueItem(tdlItem.id)
          if (queueItem) {
            queueItem.downloaded_size = tdlItem.downloaded_size
            queueItem.progress = tdlItem.progress
            // 同步状态
            if (tdlItem.status === 'completed') {
              queueItem.status = 'completed'
            } else if (tdlItem.status === 'failed') {
              queueItem.status = 'failed'
            } else if (tdlItem.status === 'running') {
              queueItem.status = 'downloading'
            }
          }
        }
        
        // 检查是否全部完成
        if (res.data.status === 'completed') {
          stopTDLProgressPolling()
          tdlMode.value = false
          alert('✅ TDL 下载完成')
        }
      }
    } catch (err) {
      console.error('获取 TDL 进度失败:', err)
    }
  }, 1500)
}

function stopTDLProgressPolling() {
  if (tdlProgressTimer) {
    clearInterval(tdlProgressTimer)
    tdlProgressTimer = null
  }
}

function findQueueItem(itemId) {
  const allItems = [
    ...queue.value.downloading,
    ...queue.value.waiting,
    ...queue.value.failed,
    ...queue.value.completed
  ]
  return allItems.find(item => item.id === itemId)
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
  fetchConcurrency()  // 获取并发配置
  refreshTimer = setInterval(fetchData, 2000)
})

onUnmounted(() => { 
  if (refreshTimer) clearInterval(refreshTimer)
  stopTDLProgressPolling()
})
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

/* 统一工具栏布局 (v1.6.7.2) */
.list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: white;
  border-bottom: 1.5px solid #f1f5f9;
  gap: 16px;
}

.flex-wrap { flex-wrap: wrap; }

/* 紧凑型并发控制 */
.concurrency-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #f8fafc;
  padding: 6px 14px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
}

.mini-control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ctrl-label {
  font-size: 0.75rem;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.mini-stepper {
  display: flex;
  align-items: center;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  overflow: hidden;
}

.mini-stepper button {
  width: 24px;
  height: 24px;
  border: none;
  background: #f1f5f9;
  cursor: pointer;
  font-weight: bold;
  transition: all 0.2s;
}

.mini-stepper button:hover:not(:disabled) { background: #e2e8f0; }
.mini-stepper .ctrl-val {
  min-width: 24px;
  text-align: center;
  font-size: 0.85rem;
  font-weight: 700;
  color: #0f172a;
}

.v-divider-mini {
  width: 1px;
  height: 14px;
  background: #cbd5e1;
}

.mini-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.mini-toggle .toggle-text {
  font-size: 0.8rem;
  font-weight: 600;
  color: #334155;
}

.active-task-info {
  font-size: 0.8rem;
  font-weight: 700;
  color: #3b82f6;
  background: #eff6ff;
  padding: 4px 10px;
  border-radius: 20px;
  margin-right: 8px;
}

/* 移除旧的 summary-grid 和 filter-tabs 相关样式 */
.summary-grid, .filter-tabs-wrapper { display: none; }

.toggle-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 0.9rem;
  font-weight: 700;
  color: #1e293b;
}

.toggle-label input { width: 16px; height: 16px; cursor: pointer; }

.main-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

/* 下拉菜单 */
.action-dropdown {
  position: relative;
  display: inline-block;
}

.dropdown-menu {
  display: none;
  position: absolute;
  top: 100%;
  left: 0;
  background: white;
  min-width: 160px;
  box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1);
  border-radius: 12px;
  padding: 8px;
  z-index: 100;
  border: 1px solid #e2e8f0;
  margin-top: 8px;
}

.action-dropdown:hover .dropdown-menu {
  display: block;
}

.dropdown-menu button {
  width: 100%;
  text-align: left;
  padding: 10px 16px;
  border: none;
  background: transparent;
  font-size: 0.85rem;
  font-weight: 600;
  border-radius: 8px;
  cursor: pointer;
  color: #475569;
  transition: all 0.2s;
}

.dropdown-menu button:hover {
  background: #f1f5f9;
  color: #3b82f6;
}

.danger-text { color: #ef4444 !important; }

.control-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.control-group label {
  font-size: 0.7rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stepper {
  display: flex;
  align-items: center;
  gap: 0;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}

.stepper button {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  font-size: 1.1rem;
  font-weight: 600;
  color: #3b82f6;
  cursor: pointer;
  transition: all 0.15s;
}

.stepper button:hover:not(:disabled) {
  background: #eff6ff;
}

.stepper button:disabled {
  color: #cbd5e1;
  cursor: not-allowed;
}

.stepper .value {
  min-width: 32px;
  text-align: center;
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e293b;
}

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
  padding: 12px 16px;
  border-bottom: 1px solid #f4f4f5;
}

.toolbar-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.toolbar-left, .toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
}

.toolbar-status {
  font-size: 0.75rem;
  font-weight: 600;
  color: #3b82f6;
  padding: 4px 10px;
  background: #eff6ff;
  border-radius: 12px;
}

.toolbar-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}
.toolbar-toggle input { display: none; }
.toolbar-toggle:hover { background: #e2e8f0; }
.toolbar-toggle:has(input:checked) { background: #3b82f6; color: white; border-color: #3b82f6; }
.toolbar-toggle.tdl:has(input:checked) { background: linear-gradient(135deg, #8b5cf6, #6366f1); border-color: #7c3aed; }

.toolbar-btn {
  padding: 4px 10px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}
.toolbar-btn:hover { background: #e2e8f0; border-color: #3b82f6; color: #3b82f6; }

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

/* TDL 模式开关 */
.tdl-mode-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s;
  margin-right: 8px;
}
.tdl-mode-toggle input { display: none; }
.tdl-mode-toggle .toggle-icon { font-size: 0.9rem; }
.tdl-mode-toggle .toggle-label-text { font-size: 0.75rem; font-weight: 700; color: #64748b; }
.tdl-mode-toggle:hover { background: #e2e8f0; }
.tdl-mode-toggle.active {
  background: linear-gradient(135deg, #8b5cf6, #6366f1);
  border-color: #7c3aed;
}
.tdl-mode-toggle.active .toggle-label-text { color: white; }

/* 队列选择 Tab */
.queue-tabs {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.queue-tabs button {
  padding: 6px 14px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: white;
  font-size: 0.8rem;
  font-weight: 500;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.queue-tabs button:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
}

.queue-tabs button.active {
  background: #3b82f6;
  border-color: #2563eb;
  color: white;
  box-shadow: 0 2px 4px rgba(59, 130, 246, 0.2);
}

/* 扫描状态迷你条 (v1.6.4) */
.scanning-status-mini {
  margin: 12px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 12px;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.s-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid #3b82f6;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.s-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
  color: #0369a1;
  font-weight: 500;
  flex: 1;
}

.s-chat {
  font-weight: 700;
  color: #0c4a6e;
  max-width: 150px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.s-msg {
  margin-left: auto;
  font-family: monospace;
  background: #e0f2fe;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.75rem;
}

/* 校验结果提示 (v1.6.4) */
.verify-result-alert {
  margin-top: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 8px 12px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.v-icon { font-size: 1rem; }
.v-text { font-size: 0.8rem; color: #475569; line-height: 1.4; flex: 1; }

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 640px) {
  .actions-panel { flex-direction: column; align-items: stretch; gap: 20px; }
  .summary-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
  .queue-item { flex-direction: column; gap: 12px; }
  .item-actions { justify-content: flex-end; border-top: 1px dashed #f4f4f5; padding-top: 10px; }
  .list-toolbar { flex-direction: column; align-items: stretch; gap: 12px; }
  .filter-tabs { overflow-x: auto; }
}
</style>
