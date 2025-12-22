<template>
  <div class="fade-in">
    <div class="page-header">
      <div class="header-text">
        <h1>📋 下载进度</h1>
        <p class="subtitle">实时管理您的 Telegram 导出队列</p>
      </div>
      <div class="header-actions">
        <button @click="pauseAll" class="btn-premium ghost sm" :disabled="runningCount === 0">⏸ 暂停所有</button>
        <button @click="resumeAll" class="btn-premium ghost sm" :disabled="pausedCount === 0">▶ 恢复所有</button>
        <button @click="removeCompleted" class="btn-premium danger sm" :disabled="completedCount === 0">🗑 清理已完成</button>
      </div>
    </div>

    <!-- 核心统计概览 -->
    <div class="stats-ribbon">
      <div class="stat-pill">
        <span class="p-icon">📦</span>
        <span class="p-label">总任务: {{ tasks.length }}</span>
      </div>
      <div class="stat-pill success">
        <span class="p-icon">✅</span>
        <span class="p-label">已完成: {{ completedCount }}</span>
      </div>
      <div class="stat-pill info" :class="{ pulse: runningCount > 0 }">
        <span class="p-icon">⚡</span>
        <span class="p-label">活跃中: {{ runningCount }}</span>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="!loading && tasks.length === 0" class="empty-state animate-fade">
      <div class="empty-icon">📂</div>
      <h3>暂无导出任务</h3>
      <p>快去创建一个新的导出任务吧！</p>
      <router-link to="/export" class="btn-premium">📥 新建导出</router-link>
    </div>

    <!-- 任务列表 -->
    <div v-else class="tasks-grid">
      <div v-for="task in tasks" :key="task.id" class="task-premium-card" :class="task.status">
        <div class="task-inner">
          <div class="task-main-info">
            <div class="t-head">
              <div class="t-title-row">
                <h3 class="t-name text-truncate">{{ task.name }}</h3>
                <span class="t-status-pill" :class="task.status">{{ statusText[task.status] || task.status }}</span>
              </div>
              <p class="t-date">创建于 {{ formatDate(task.created_at) }}</p>
            </div>

            <!-- 主进度展示 -->
            <div class="t-progress-section">
              <div class="t-progress-header">
                <span class="t-percent">{{ (task.progress || 0).toFixed(1) }}%</span>
                <span class="t-eta" v-if="task.status === 'running' && stats[task.id]?.etr">
                  剩余时间约为: {{ stats[task.id].etr }}
                </span>
                <span class="t-speed" v-if="task.status === 'running' && stats[task.id]?.speed">
                  {{ stats[task.id].speed }} MB/s
                </span>
              </div>
              <div class="t-progress-track">
                <div class="t-progress-fill" :style="{ width: task.progress + '%' }" :class="task.status"></div>
              </div>
            </div>

            <!-- 详细指标 -->
            <div class="t-metrics">
              <div class="m-item">
                <span class="m-icon">📨</span>
                <span class="m-data">消息: <b>{{ task.processed_messages }}</b></span>
              </div>
              <div class="m-item">
                <span class="m-icon">📁</span>
                <span class="m-data">媒体: <b>{{ task.downloaded_media }} / {{ task.total_media }}</b></span>
              </div>
              <div class="m-item">
                <span class="m-icon">💾</span>
                <span class="m-data">大小: <b>{{ formatSize(task.downloaded_size) }}</b></span>
              </div>
            </div>
          </div>

          <!-- 侧边操作栏 -->
          <div class="task-side-actions">
            <button v-if="['running', 'extracting'].includes(task.status)" @click="pauseTask(task.id)" class="a-btn v-warn" title="暂停">⏸</button>
            <button v-if="task.status === 'paused'" @click="resumeTask(task.id)" class="a-btn v-success" title="继续">▶</button>
            <button v-if="['extracting', 'running', 'paused'].includes(task.status)" @click="cancelTask(task.id)" class="a-btn v-danger" title="取消">✖</button>
            <button v-if="task.status === 'completed'" @click="resumeTask(task.id)" class="a-btn v-primary" title="重新运行">🔄</button>
            <button v-if="['completed', 'failed', 'cancelled'].includes(task.status)" @click="deleteTask(task.id)" class="a-btn v-outline" title="删除">🗑</button>
            <a v-if="task.status === 'completed'" :href="'/exports/' + task.id" target="_blank" class="a-btn v-info" title="浏览文件">📂</a>
          </div>
        </div>

        <!-- 文件详情展开 (仅在活跃状态显示) -->
        <div v-if="task.download_queue?.length > 0" class="task-details">
          <button class="details-toggle" @click="toggleDetailed(task.id)">
            文件列表明细 ({{ task.download_queue.length }} 个) {{ isDetailedExpanded(task) ? '▲' : '▼' }}
          </button>
          
          <div v-if="isDetailedExpanded(task)" class="details-list-wrap animate-fade">
            <div v-for="item in task.download_queue.slice(0, 50)" :key="item.id" class="queue-item">
              <div class="q-info">
                <span class="q-name">{{ item.file_name }}</span>
                <span class="q-percent">{{ item.progress.toFixed(0) }}%</span>
              </div>
              <div class="q-bar-wrap">
                <div class="q-bar" :style="{ width: item.progress + '%' }" :class="item.status"></div>
                <span class="q-status-text">{{ item.status }}</span>
                <button v-if="['failed', 'completed'].includes(item.status)" class="q-retry-btn" @click="retryFile(task.id, item.id)">
                  {{ item.status === 'failed' ? '重试' : '重新下载' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 加载遮罩 -->
    <div v-if="loading && tasks.length === 0" class="global-loading">
      <div class="loader-ring"></div>
      <p>正在同步任务状态...</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, reactive } from 'vue'
import axios from 'axios'

const loading = ref(true)
const tasks = ref([])
const expandedDetailed = ref({})
const stats = reactive({})

const statusText = {
  extracting: '扫描中',
  pending: '等待中',
  running: '正在下载',
  completed: '已完成',
  failed: '失败',
  cancelled: '已停止',
  paused: '已暂停'
}

function getAuthHeader() { return { Authorization: `Bearer ${localStorage.getItem('token')}` } }

function isDetailedExpanded(task) {
  if (expandedDetailed.value[task.id] !== undefined) return expandedDetailed.value[task.id]
  return ['running', 'paused', 'extracting'].includes(task.status)
}

function toggleDetailed(taskId) { expandedDetailed.value[taskId] = !expandedDetailed.value[taskId] }

// ETR & Speed Calculation
const lastProgress = {}
function updateLiveStats() {
  tasks.value.forEach(task => {
    if (task.status !== 'running') return
    const prev = lastProgress[task.id] || { progress: 0, time: Date.now(), size: 0 }
    const now = Date.now()
    const dt = (now - prev.time) / 1000
    if (dt < 1) return

    const ds = (task.downloaded_size - prev.size) / (1024 * 1024)
    const speed = ds / dt
    
    if (!stats[task.id]) stats[task.id] = {}
    stats[task.id].speed = speed > 0 ? speed.toFixed(1) : '0.0'
    
    if (speed > 0.01) {
      const remainingSize = (task.total_media_size || 0) - task.downloaded_size
      const etrSeconds = (remainingSize / (1024 * 1024)) / speed
      if (etrSeconds > 0) {
        const h = Math.floor(etrSeconds / 3600)
        const m = Math.floor((etrSeconds % 3600) / 60)
        const s = Math.floor(etrSeconds % 60)
        stats[task.id].etr = h > 0 ? `${h}h ${m}m` : (m > 0 ? `${m}m ${s}s` : `${s}s`)
      }
    }
    
    lastProgress[task.id] = { progress: task.progress, time: now, size: task.downloaded_size }
  })
}

async function fetchTasks() {
  try {
    const res = await axios.get('/api/export/tasks', { headers: getAuthHeader() })
    tasks.value = res.data.reverse()
    updateLiveStats()
  } catch (err) { console.error('Fetch failed:', err) }
  finally { loading.value = false }
}

// 统计
const completedCount = computed(() => tasks.value.filter(t => t.status === 'completed').length)
const pendingCount = computed(() => tasks.value.filter(t => ['extracting', 'pending', 'running', 'paused'].includes(t.status)).length)
const runningCount = computed(() => tasks.value.filter(t => ['extracting', 'running'].includes(t.status)).length)
const pausedCount = computed(() => tasks.value.filter(t => t.status === 'paused').length)

// Actions
async function pauseTask(id) { await axios.post(`/api/export/${id}/pause`, {}, { headers: getAuthHeader() }); fetchTasks() }
async function resumeTask(id) { await axios.post(`/api/export/${id}/resume`, {}, { headers: getAuthHeader() }); fetchTasks() }
async function cancelTask(id) { if(confirm('确定取消该任务？')) { await axios.post(`/api/export/${id}/cancel`, {}, { headers: getAuthHeader() }); fetchTasks() } }
async function deleteTask(id) { if(confirm('确定删除该记录？')) { await axios.delete(`/api/export/${id}`, { headers: getAuthHeader() }); tasks.value = tasks.value.filter(t => t.id !== id) } }
async function retryFile(taskId, fileId) { await axios.post(`/api/export/${taskId}/retry_file/${fileId}`, {}, { headers: getAuthHeader() }); fetchTasks() }

async function pauseAll() { tasks.value.filter(t => ['running', 'extracting'].includes(t.status)).forEach(t => pauseTask(t.id)) }
async function resumeAll() { tasks.value.filter(t => t.status === 'paused').forEach(t => resumeTask(t.id)) }
async function removeCompleted() { if(confirm('清空已完成的历史记录？')) { tasks.value.filter(t => t.status === 'completed').forEach(t => deleteTask(t.id)) } }

function formatSize(b) { if(!b) return '0 B'; const u=['B','KB','MB','GB','TB']; let i=0; while(b>=1024 && i<u.length-1){b/=1024;i++} return b.toFixed(1)+' '+u[i] }
function formatDate(s) { return s ? new Date(s).toLocaleString('zh-CN') : '' }

let intervalId = null
onMounted(() => { fetchTasks(); intervalId = setInterval(fetchTasks, 3000) })
onUnmounted(() => clearInterval(intervalId))
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 30px; }
.header-text h1 { font-size: 2.2rem; font-weight: 800; margin-bottom: 4px; }
.subtitle { color: #71717a; font-size: 1rem; }
.header-actions { display: flex; gap: 10px; }

.stats-ribbon { display: flex; gap: 15px; margin-bottom: 25px; }
.stat-pill { background: white; padding: 8px 16px; border-radius: 50px; border: 1px solid #f4f4f5; display: flex; align-items: center; gap: 8px; font-weight: 700; font-size: 0.85rem; color: #3f3f46; box-shadow: 0 2px 4px rgba(0,0,0,0.02); }
.stat-pill.success { color: #166534; background: #f0fdf4; border-color: #dcfce7; }
.stat-pill.info { color: #1e40af; background: #eff6ff; border-color: #dbeafe; }

@keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.6; } 100% { opacity: 1; } }
.pulse { animation: pulse 2s infinite; }

.tasks-grid { display: flex; flex-direction: column; gap: 20px; }
.task-premium-card { background: white; border-radius: 20px; border: 1px solid #f4f4f5; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.03); overflow: hidden; transition: transform 0.2s, box-shadow 0.2s; }
.task-premium-card:hover { transform: translateY(-2px); box-shadow: 0 12px 20px -8px rgba(0,0,0,0.08); }

.task-inner { display: flex; padding: 24px; gap: 24px; }
.task-main-info { flex: 1; min-width: 0; }

.t-head { margin-bottom: 20px; }
.t-title-row { display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }
.t-name { font-size: 1.25rem; font-weight: 800; color: #18181b; }
.t-date { font-size: 0.8rem; color: #a1a1aa; font-weight: 500; }

.t-status-pill { padding: 4px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: 800; text-transform: uppercase; }
.t-status-pill.running { background: #eff6ff; color: #2563eb; }
.t-status-pill.completed { background: #f0fdf4; color: #16a34a; }
.t-status-pill.paused { background: #fffbeb; color: #d97706; }
.t-status-pill.failed { background: #fef2f2; color: #dc2626; }

.t-progress-section { margin-bottom: 20px; }
.t-progress-header { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 8px; }
.t-percent { font-size: 1.5rem; font-weight: 900; color: #18181b; }
.t-eta, .t-speed { font-size: 0.8rem; font-weight: 600; color: #71717a; }
.t-speed { color: var(--primary); }

.t-progress-track { height: 10px; background: #f4f4f5; border-radius: 5px; overflow: hidden; }
.t-progress-fill { height: 100%; border-radius: 5px; transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1); background: #3b82f6; }
.t-progress-fill.completed { background: #22c55e; }
.t-progress-fill.failed { background: #ef4444; }
.t-progress-fill.paused { background: #f59e0b; }

.t-metrics { display: flex; gap: 20px; }
.m-item { display: flex; align-items: center; gap: 6px; color: #52525b; font-size: 0.85rem; }
.m-data b { color: #18181b; }

.task-side-actions { display: flex; flex-direction: column; gap: 8px; }
.a-btn { width: 42px; height: 42px; border-radius: 12px; border: none; font-size: 1.1rem; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s; background: #f4f4f5; color: #71717a; }
.a-btn:hover { transform: scale(1.05); }
.a-btn.v-success:hover { background: #dcfce7; color: #166534; }
.a-btn.v-warn:hover { background: #fef3c7; color: #92400e; }
.a-btn.v-danger:hover { background: #fecaca; color: #991b1b; }
.a-btn.v-primary { background: #eff6ff; color: #1e40af; }
.a-btn.v-info { background: #f0fdf4; color: #166534; text-decoration: none; }

.task-details { border-top: 1px solid #f4f4f5; background: #fafafa; }
.details-toggle { width: 100%; padding: 12px; border: none; background: none; font-size: 0.8rem; font-weight: 700; color: #71717a; cursor: pointer; text-align: left; transition: background 0.2s; }
.details-toggle:hover { background: #f4f4f5; }

.details-list-wrap { padding: 0 16px 16px; max-height: 300px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.queue-item { padding: 10px; background: white; border-radius: 12px; border: 1px solid #f1f1f1; }
.q-info { display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 0.75rem; font-weight: 600; }
.q-name { font-family: monospace; color: #52525b; }
.q-bar-wrap { display: flex; align-items: center; gap: 10px; }
.q-bar { flex: 1; height: 4px; background: #f4f4f5; border-radius: 2px; position: relative; overflow: hidden; }
.q-bar::after { content: ''; position: absolute; left: 0; top: 0; height: 100%; width: var(--w); background: var(--primary); transition: width 0.3s; } /* Dynamic width handled by inline style */
/* Actually using direct style on q-bar child: */
.q-bar { position: relative; }
.q-bar::after { display: none; }
.q-bar .q-fill { height: 100%; background: #3b82f6; } /* Reference */

/* Using a real child for q-bar fill */
.q-bar { height: 4px; background: #f4f4f5; }
.q-bar div { height: 100%; transition: width 0.3s; background: #3b82f6; }
.q-bar div.completed { background: #22c55e; }
.q-bar div.failed { background: #ef4444; }

.q-status-text { font-size: 0.65rem; color: #a1a1aa; text-transform: uppercase; font-weight: 800; min-width: 60px; }
.q-retry-btn { padding: 2px 8px; font-size: 0.65rem; font-weight: 700; border-radius: 4px; border: 1px solid #e4e4e7; background: white; cursor: pointer; white-space: nowrap; }
.q-retry-btn:hover { background: #f4f4f5; }

.empty-state { padding: 60px; text-align: center; color: #71717a; }
.empty-icon { font-size: 4rem; margin-bottom: 20px; opacity: 0.5; }

.animate-fade { animation: fadeIn 0.4s ease-out; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

.text-truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
