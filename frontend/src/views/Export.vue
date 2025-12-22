<template>
  <div class="fade-in">
    <div class="page-header">
      <h1>📥 Create Export Task</h1>
      <p class="subtitle">Fast, reliable, and precise message backups</p>
    </div>
    
    <!-- Modern Step Indicator -->
    <div class="step-container">
      <div class="step-progress-bar">
        <div class="progress-fill" :style="{ width: ((step - 1) / 3 * 100) + '%' }"></div>
      </div>
      <div class="steps">
        <div v-for="i in 4" :key="i" :class="['step-item', step >= i ? 'active' : '', step === i ? 'current' : '']">
          <div class="step-number">{{ i }}</div>
          <span class="step-label">{{ stepLabels[i-1] }}</span>
        </div>
      </div>
    </div>
    
    <!-- Step 1: Chat Types -->
    <div v-if="step === 1" class="step-content">
      <div class="config-grid">
        <div class="config-card">
          <div class="card-title">
            <i class="icon">💬</i>
            <h3>History Settings</h3>
          </div>
          <div class="selection-grid">
            <label class="custom-checkbox">
              <input type="checkbox" v-model="options.private_chats">
              <div class="checkbox-box">
                <span class="emoji">👤</span>
                <span class="label">Private Chats</span>
              </div>
            </label>
            <label class="custom-checkbox">
              <input type="checkbox" v-model="options.bot_chats">
              <div class="checkbox-box">
                <span class="emoji">🤖</span>
                <span class="label">Bots</span>
              </div>
            </label>
            <label class="custom-checkbox">
              <input type="checkbox" v-model="options.private_groups">
              <div class="checkbox-box">
                <span class="emoji">👥</span>
                <span class="label">Groups</span>
              </div>
            </label>
            <label class="custom-checkbox">
              <input type="checkbox" v-model="options.private_channels">
              <div class="checkbox-box">
                <span class="emoji">📢</span>
                <span class="label">Channels</span>
              </div>
            </label>
            <label class="custom-checkbox">
              <input type="checkbox" v-model="options.public_groups">
              <div class="checkbox-box">
                <span class="emoji">🌐</span>
                <span class="label">Pub. Groups</span>
              </div>
            </label>
            <label class="custom-checkbox">
              <input type="checkbox" v-model="options.public_channels">
              <div class="checkbox-box">
                <span class="emoji">📣</span>
                <span class="label">Pub. Channels</span>
              </div>
            </label>
          </div>
          <div class="card-footer">
            <label class="form-checkbox">
              <input type="checkbox" v-model="options.only_my_messages">
              <span>Only my messages</span>
            </label>
          </div>
        </div>

        <div class="config-card secondary">
          <div class="card-title">
            <i class="icon">📌</i>
            <h3>Advanced Selection</h3>
          </div>
          
          <div class="option-group">
            <div class="option-header" @click="enableSpecificChats = !enableSpecificChats">
              <input type="checkbox" v-model="enableSpecificChats" @click.stop>
              <h4>Specific Chats</h4>
            </div>
            <div v-if="enableSpecificChats" class="option-body animate-slide">
              <p>Paste IDs or links. We'll handle the rest.</p>
              <div class="input-stack">
                <input v-model="specificChatsInput" @input="parseSpecificChats" class="modern-input" placeholder="e.g. -100123... or t.me/join...">
                <div v-if="parsedChatIds.length > 0" class="tag-cloud">
                  <span v-for="(id, idx) in parsedChatIds" :key="idx" class="modern-tag" @click="removeChatId(idx)">{{ id }} <span class="close">×</span></span>
                </div>
              </div>
            </div>
          </div>

          <div class="option-group">
            <div class="option-header" @click="enableMessageRange = !enableMessageRange">
              <input type="checkbox" v-model="enableMessageRange" @click.stop>
              <h4>Message Range</h4>
            </div>
            <div v-if="enableMessageRange" class="option-body animate-slide">
              <div class="range-inputs">
                <div class="range-field">
                  <label>From ID</label>
                  <input v-model.number="options.message_from" type="number" class="modern-input short" min="1">
                </div>
                <div class="range-sep">to</div>
                <div class="range-field">
                  <label>Until (0=Latest)</label>
                  <input v-model.number="options.message_to" type="number" class="modern-input short" min="0">
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      
      <div class="action-bar">
        <router-link to="/dashboard" class="btn-ghost">Cancel</router-link>
        <button @click="step = 2" class="btn-premium">Next Step <i class="btn-icon">→</i></button>
      </div>
    </div>
    
    <!-- Step 2: Media Types -->
    <div v-if="step === 2" class="step-content">
      <div class="config-card">
        <div class="card-title">
          <i class="icon">📁</i>
          <h3>Media Files to Export</h3>
        </div>
        <div class="selection-grid large">
          <label v-for="(val, key) in mediaTypes" :key="key" class="media-checkbox">
            <input type="checkbox" v-model="options[key]">
            <div class="media-box">
              <span class="media-emoji">{{ val.icon }}</span>
              <div class="media-info">
                <span class="media-label">{{ val.label }}</span>
                <span class="media-desc">{{ val.desc }}</span>
              </div>
            </div>
          </label>
        </div>
      </div>
      
      <div class="action-bar">
        <button @click="step = 1" class="btn-ghost">← Back</button>
        <button @click="step = 3" class="btn-premium">Next Step <i class="btn-icon">→</i></button>
      </div>
    </div>
    
    <!-- Step 3: Other Options -->
    <div v-if="step === 3" class="step-content">
      <div class="config-grid">
        <div class="config-card">
          <div class="card-title"><i class="icon">⚙️</i><h3>Download Configuration</h3></div>
          
          <div class="settings-stack">
            <div class="setting-item">
              <label>Save Path</label>
              <input v-model="options.export_path" class="modern-input" placeholder="/downloads">
            </div>
            
            <div class="setting-item">
              <label>Export Format</label>
              <div class="radio-pill-group">
                <label v-for="fmt in ['html', 'json', 'both']" :key="fmt" :class="['radio-pill', options.export_format === fmt ? 'selected' : '']">
                  <input type="radio" v-model="options.export_format" :value="fmt">
                  <span>{{ fmt.toUpperCase() }}</span>
                </label>
              </div>
            </div>

            <div class="setting-item horizontal">
              <div class="field-item">
                <label>Max Concurrency</label>
                <div class="number-stepper">
                  <button @click="options.max_concurrent_downloads = Math.max(1, options.max_concurrent_downloads - 1)">-</button>
                  <input v-model.number="options.max_concurrent_downloads" type="number" readonly>
                  <button @click="options.max_concurrent_downloads = Math.min(10, options.max_concurrent_downloads + 1)">+</button>
                </div>
              </div>
              <div class="field-item">
                <label>Resume Download</label>
                <div class="toggle-switch">
                  <input type="checkbox" v-model="options.resume_download">
                  <span class="slider"></span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="config-card secondary">
          <div class="card-title"><i class="icon">📅</i><h3>Time Range</h3></div>
          <div class="date-range-container">
            <div class="date-input-wrap">
              <label>Start From</label>
              <input type="date" v-model="dateFrom" class="modern-input date">
            </div>
            <div class="date-input-wrap">
              <label>Until Date</label>
              <input type="date" v-model="dateTo" class="modern-input date">
            </div>
          </div>
          <p class="hint">Leave empty to export all history</p>
        </div>
      </div>
      
      <div class="action-bar">
        <button @click="step = 2" class="btn-ghost">← Back</button>
        <button @click="step = 4" class="btn-premium">Next Step <i class="btn-icon">→</i></button>
      </div>
    </div>
    
    <!-- Step 4: Finalize -->
    <div v-if="step === 4" class="step-content">
      <div class="config-card highlight">
        <div class="card-title center">
          <i class="icon hero">✨</i>
          <h2>Ready to Launch</h2>
        </div>
        
        <div class="task-naming">
          <input v-model="taskName" class="modern-input hero" placeholder="Give your task a name (e.g. My Backup)">
        </div>

        <div class="summary-box">
          <div class="summaries">
            <div class="summary-item">
              <span class="s-label">Scope</span>
              <span class="s-value">{{ getSummaryText('chats') }}</span>
            </div>
            <div class="summary-item">
              <span class="s-label">Content</span>
              <span class="s-value">{{ getSummaryText('media') }}</span>
            </div>
            <div class="summary-item">
              <span class="s-label">Destination</span>
              <span class="s-value">{{ options.export_path }} ({{ options.export_format.toUpperCase() }})</span>
            </div>
          </div>
        </div>
        
        <div v-if="error" class="error-toast">
          {{ error }}
        </div>
        
        <div class="final-actions">
          <button @click="step = 3" class="btn-ghost large">Back to Edit</button>
          <button @click="startExport" class="btn-premium hero" :disabled="loading">
            {{ loading ? 'Initializing...' : '🚀 Launch Export' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

const router = useRouter()
const step = ref(1)
const loading = ref(false)
const error = ref('')
const taskName = ref('')
const specificChatsInput = ref('')
const filterMessagesInput = ref('')
const dateFrom = ref('')
const dateTo = ref('')

const stepLabels = ['Setup Scope', 'Media Selection', 'Performance', 'Final Review']

const mediaTypes = {
  photos: { label: 'Photos', icon: '🖼️', desc: 'Standard images and profile pics' },
  videos: { label: 'Videos', icon: '🎬', desc: 'Video files and attachments' },
  voice_messages: { label: 'Voice', icon: '🎤', desc: 'Audio voice messages' },
  video_messages: { label: 'Video Msg', icon: '📹', desc: 'Round video notes' },
  stickers: { label: 'Stickers', icon: '🎨', desc: 'Animated and static stickers' },
  gifs: { label: 'Animations', icon: '🎞️', desc: 'GIFs and autoplaying videos' },
  files: { label: 'Documents', icon: '📎', desc: 'Generic files and documents' }
}

// 启用开关
const enableSpecificChats = ref(false)
const enableMessageRange = ref(false)
const enableMessageFilter = ref(false)

// 解析后的 ID 列表
const parsedChatIds = ref([])
const parsedMessageIds = ref([])

// 智能解析: 从任何文本中提取数字
function parseNumbers(text) {
  const matches = text.match(/-?\d+/g)
  return matches ? [...new Set(matches.map(n => parseInt(n)))].filter(n => !isNaN(n)) : []
}

function parseSpecificChats() {
  parsedChatIds.value = parseNumbers(specificChatsInput.value)
}

function parseFilterMessages() {
  parsedMessageIds.value = parseNumbers(filterMessagesInput.value).filter(n => n > 0)
}

function removeChatId(idx) {
  parsedChatIds.value.splice(idx, 1)
}

function removeMessageId(idx) {
  parsedMessageIds.value.splice(idx, 1)
}

const options = reactive({
  // 聊天类型
  private_chats: true,
  bot_chats: false,
  private_groups: true,
  private_groups: true,
  private_channels: true,
  public_groups: false,
  public_channels: false,
  only_my_messages: false,
  specific_chats: [],
  
  // 消息范围
  message_from: 1,
  message_to: 0,  // 0 = 最新
  
  // 断点续传
  resume_download: true,
  skip_existing: true,
  
  // 媒体类型
  photos: true,
  videos: true,
  voice_messages: true,
  video_messages: true,
  stickers: false,
  gifs: true,
  files: true,
  
  // 其他
  export_path: '/downloads',
  export_format: 'html',
  
  // 下载设置
  max_concurrent_downloads: 10,
  download_threads: 10,
  download_speed_limit: 0,
  
  // 消息过滤
  filter_mode: 'skip',
  filter_messages: []
})

const formatText = {
  html: 'Human Readable HTML',
  json: 'Machine Readable JSON',
  both: 'Both HTML & JSON'
}

function getSummaryText(type) {
  if (type === 'chats') {
    const items = []
    if (options.private_chats) items.push('Private')
    if (options.bot_chats) items.push('Bots')
    if (options.private_groups) items.push('Groups')
    if (options.private_channels) items.push('Channels')
    if (options.public_groups) items.push('Pub. Groups')
    if (options.public_channels) items.push('Pub. Channels')
    return items.join(', ') || 'No Scope selected'
  }
  if (type === 'media') {
    const items = []
    if (options.photos) items.push('Photos')
    if (options.videos) items.push('Videos')
    if (options.voice_messages) items.push('Voice')
    if (options.video_messages) items.push('Round Video')
    if (options.stickers) items.push('Stickers')
    if (options.gifs) items.push('GIFs')
    if (options.files) items.push('Files')
    return items.join(', ') || 'No Media selected'
  }
  return ''
}

async function startExport() {
  if (!taskName.value) {
    error.value = 'Please enter a task name'
    return
  }
  
  loading.value = true
  error.value = ''
  
  try {
    // 处理指定聊天
    if (enableSpecificChats.value && parsedChatIds.value.length > 0) {
      options.specific_chats = parsedChatIds.value
    }
    
    // 处理消息范围
    if (!enableMessageRange.value) {
      options.message_from = 1
      options.message_to = 0
    }
    
    // 处理日期
    if (dateFrom.value) {
      options.date_from = new Date(dateFrom.value).toISOString()
    }
    if (dateTo.value) {
      options.date_to = new Date(dateTo.value).toISOString()
    }
    
    // 处理消息过滤
    if (enableMessageFilter.value && parsedMessageIds.value.length > 0) {
      options.filter_messages = parsedMessageIds.value
    } else {
      options.filter_mode = 'none'
    }
    
    const headers = { Authorization: `Bearer ${localStorage.getItem('token')}` }
    
    // 创建任务
    const createRes = await axios.post(
      `/api/export/create?name=${encodeURIComponent(taskName.value)}`,
      options,
      { headers }
    )
    
    // 启动任务
    await axios.post(`/api/export/${createRes.data.id}/start`, {}, { headers })
    
    // 跳转到管理页面
    router.push('/downloads')
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to create task'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.page-header {
  margin-bottom: 40px;
  text-align: center;
}

.page-header h1 {
  font-size: 2.5rem;
  font-weight: 800;
  background: linear-gradient(135deg, var(--primary), #a855f7);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 8px;
}

.subtitle {
  color: #71717a;
  font-size: 1.1rem;
}

/* Step Indicator */
.step-container {
  max-width: 800px;
  margin: 0 auto 50px;
  position: relative;
}

.step-progress-bar {
  position: absolute;
  top: 20px;
  left: 40px;
  right: 40px;
  height: 4px;
  background: #e4e4e7;
  z-index: 1;
  border-radius: 2px;
}

.progress-fill {
  height: 100%;
  background: var(--primary);
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.steps {
  display: flex;
  justify-content: space-between;
  position: relative;
  z-index: 2;
}

.step-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.step-number {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: white;
  border: 2px solid #e4e4e7;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: #a1a1aa;
  transition: all 0.3s ease;
  box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
}

.step-item.active .step-number {
  border-color: var(--primary);
  color: var(--primary);
}

.step-item.current .step-number {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
  transform: scale(1.1);
}

.step-label {
  font-size: 0.9rem;
  font-weight: 600;
  color: #71717a;
}

.step-item.active .step-label {
  color: #18181b;
}

/* Config Grid */
.config-grid {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 24px;
  margin-bottom: 30px;
}

@media (max-width: 900px) {
  .config-grid { grid-template-columns: 1fr; }
}

.config-card {
  background: white;
  border-radius: 24px;
  padding: 30px;
  border: 1px solid #f4f4f5;
  box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.04);
}

.config-card.secondary {
  background: #fafafa;
}

.config-card.highlight {
  max-width: 700px;
  margin: 0 auto;
  text-align: center;
  background: linear-gradient(to bottom right, #ffffff, #fdf4ff);
}

.card-title {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}

.card-title.center { justify-content: center; flex-direction: column; }

.icon {
  font-size: 1.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  background: #f4f4f5;
  border-radius: 10px;
}

.icon.hero {
  font-size: 3rem;
  width: 80px;
  height: 80px;
  background: #f0abfc22;
  border-radius: 24px;
  margin-bottom: 15px;
}

/* Selection Grids */
.selection-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.selection-grid.large {
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
}

.custom-checkbox input, .media-checkbox input { display: none; }

.checkbox-box {
  padding: 16px;
  border-radius: 16px;
  border: 2px solid #f4f4f5;
  background: #fff;
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.custom-checkbox input:checked + .checkbox-box {
  border-color: var(--primary);
  background: #fdf4ff;
}

.media-box {
  padding: 20px;
  border-radius: 20px;
  border: 2px solid #f4f4f5;
  background: #fff;
  display: flex;
  align-items: center;
  gap: 16px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.media-checkbox input:checked + .media-box {
  border-color: var(--primary);
  background: #fdf4ff;
  box-shadow: 0 4px 6px -1px var(--primary-light);
}

.media-emoji { font-size: 2rem; }
.media-label { display: block; font-weight: 700; font-size: 1.1rem; }
.media-desc { font-size: 0.85rem; color: #71717a; }

/* Advanced Inputs */
.option-group {
  background: white;
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 16px;
  border: 1px solid #f4f4f5;
}

.option-header {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
}

.option-body {
  margin-top: 15px;
  padding-top: 15px;
  border-top: 1px dashed #e4e4e7;
}

.modern-input {
  width: 100%;
  padding: 12px 16px;
  border-radius: 12px;
  border: 1.5px solid #e4e4e7;
  font-size: 1rem;
  transition: all 0.2s;
}

.modern-input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 4px #fdf4ff;
}

.modern-input.hero {
  font-size: 1.5rem;
  padding: 20px;
  text-align: center;
  font-weight: 600;
  border-radius: 20px;
}

.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.modern-tag {
  background: var(--primary);
  color: white;
  padding: 6px 12px;
  border-radius: 50px;
  font-size: 0.85rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.close { opacity: 0.7; }

/* Stepper & Toggles */
.settings-stack { display: flex; flex-direction: column; gap: 20px; }

.horizontal {
  display: flex;
  gap: 24px;
}

.number-stepper {
  display: flex;
  align-items: center;
  background: #f4f4f5;
  border-radius: 12px;
  padding: 4px;
  width: fit-content;
}

.number-stepper button {
  width: 36px;
  height: 36px;
  border: none;
  background: white;
  border-radius: 8px;
  font-weight: bold;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.number-stepper input {
  width: 40px;
  text-align: center;
  background: transparent;
  border: none;
  font-weight: 700;
}

.radio-pill-group {
  display: flex;
  gap: 10px;
  background: #f4f4f5;
  padding: 6px;
  border-radius: 14px;
}

.radio-pill {
  flex: 1;
  text-align: center;
  padding: 10px;
  cursor: pointer;
  border-radius: 10px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #71717a;
  transition: all 0.2s;
}

.radio-pill.selected {
  background: white;
  color: var(--primary);
  box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05);
}

.radio-pill input { display: none; }

/* Final Review */
.summary-box {
  background: #fafafa;
  border-radius: 20px;
  padding: 24px;
  margin-top: 24px;
}

.summary-item {
  display: flex;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid #f4f4f5;
}

.summary-item:last-child { border: none; }
.s-label { color: #71717a; font-weight: 500; }
.s-value { font-weight: 700; text-align: right; }

/* Action Bar */
.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 40px;
}

.btn-premium {
  padding: 14px 28px;
  background: var(--primary);
  color: white;
  border-radius: 16px;
  font-weight: 700;
  border: none;
  cursor: pointer;
  box-shadow: 0 10px 15px -3px rgba(168, 85, 247, 0.4);
  transition: all 0.3s;
  display: flex;
  align-items: center;
  gap: 10px;
}

.btn-premium:hover { transform: translateY(-3px); box-shadow: 0 20px 25px -5px rgba(168, 85, 247, 0.3); }

.btn-premium.hero {
  width: 100%;
  padding: 20px;
  font-size: 1.25rem;
  justify-content: center;
  margin-top: 24px;
}

.btn-ghost {
  padding: 14px 24px;
  color: #71717a;
  font-weight: 600;
  background: none;
  border: none;
  cursor: pointer;
  transition: color 0.2s;
}

.btn-ghost:hover { color: #18181b; }

.animate-slide {
  animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}

.error-toast {
  background: #fef2f2;
  color: #ef4444;
  padding: 16px;
  border-radius: 12px;
  margin-top: 20px;
  font-weight: 600;
  border: 1px solid #fee2e2;
}
</style>
