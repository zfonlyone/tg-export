<template>
  <div class="fade-in">
    <h1 style="margin-bottom: 20px;">📥 导出数据</h1>
    
    <!-- 步骤指示器 -->
    <div class="card" style="margin-bottom: 20px;">
      <div style="display: flex; justify-content: space-between;">
        <div :class="['step', step >= 1 ? 'active' : '']">1. 选择聊天类型</div>
        <div :class="['step', step >= 2 ? 'active' : '']">2. 选择媒体类型</div>
        <div :class="['step', step >= 3 ? 'active' : '']">3. 其他选项</div>
        <div :class="['step', step >= 4 ? 'active' : '']">4. 确认导出</div>
      </div>
    </div>
    
    <!-- 步骤 1: 聊天类型 -->
    <div v-if="step === 1" class="card">
      <div class="card-header">
        <h2>历史记录导出设置</h2>
      </div>

      <div style="display: flex; gap: 10px; margin-bottom: 16px;">
        <button class="btn" :class="exportMode === 'quick' ? 'btn-primary' : 'btn-outline'" @click="exportMode = 'quick'">⚡ 快速模式</button>
        <button class="btn" :class="exportMode === 'advanced' ? 'btn-primary' : 'btn-outline'" @click="exportMode = 'advanced'">🛠️ 高级模式</button>
      </div>
      
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.private_chats">
          <span>👤 私聊</span>
        </label>
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.bot_chats">
          <span>🤖 机器人对话</span>
        </label>
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.private_groups">
          <span>👥 私密群组</span>
        </label>
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.private_channels">
          <span>📢 私密频道</span>
        </label>
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.public_groups">
          <span>🌐 公开群组</span>
        </label>
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.public_channels">
          <span>📣 公开频道</span>
        </label>
      </div>
      
      <div style="margin-top: 20px; padding-top: 15px; border-top: 1px solid var(--border);">
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.only_my_messages">
          <span>只导出我的消息</span>
        </label>
      </div>
      
      <!-- 精确单条消息/文件下载 -->
      <div style="margin-top: 15px; padding: 15px; border: 1px solid var(--border); border-radius: 8px; background: rgba(59,130,246,0.04);">
        <div style="font-weight: 600; margin-bottom: 8px;">🎯 精确单条消息/文件下载</div>
        <p style="color: #666; margin-bottom: 8px; font-size: 13px;">直接粘贴 Telegram 消息链接，自动填充“指定聊天 + 单条消息范围”。适合只下载某个频道里的某一个文件。</p>
        <div style="display: flex; gap: 12px; align-items: center;">
          <input v-model="exactMessageLinkInput" class="form-input" style="flex: 1;" placeholder="例如: https://t.me/c/3450385408/1354">
          <button @click="applyExactMessageLink" class="btn btn-outline">一键填充</button>
        </div>
        <div v-if="exactMessageId && exactChatId" style="margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center;">
          <span style="font-size: 12px; color: #666;">批量快捷范围：</span>
          <button @click="applyBatchPreset('single')" class="btn btn-outline" style="padding: 6px 10px;">仅此消息</button>
          <button @click="applyBatchPreset('forward')" class="btn btn-outline" style="padding: 6px 10px;">从此消息到最新</button>
          <button @click="applyBatchPreset('backward')" class="btn btn-outline" style="padding: 6px 10px;">从 1 到此消息</button>
          <button @click="applyBatchPreset('window100')" class="btn btn-outline" style="padding: 6px 10px;">前后各 50 条</button>
        </div>
        <div v-if="exactMessageId && exactChatId" style="margin-top: 12px; display: flex; gap: 10px; flex-wrap: wrap;">
          <button @click="quickStartFromLink" class="btn btn-success">🚀 立即创建下载任务</button>
          <button @click="step = 2" class="btn btn-outline">继续微调媒体与下载设置</button>
        </div>
      </div>

      <!-- 指定聊天 -->
      <div style="margin-top: 20px; padding: 15px; border: 1px solid var(--border); border-radius: 8px;">
        <label class="form-checkbox" style="margin-bottom: 0;">
          <input type="checkbox" v-model="enableSpecificChats">
          <span style="font-weight: 600;">📌 指定聊天</span>
        </label>
        <div v-if="enableSpecificChats" style="margin-top: 12px;">
          <p style="color: #666; margin-bottom: 8px; font-size: 13px;">粘贴聊天 ID 或链接，系统会自动识别。💡 如果 ID 缺少 -100 前缀，后台将尝试自动补全。</p>
          <div style="display: flex; gap: 15px;">
            <input v-model="specificChatsInput" @input="parseSpecificChats" class="form-input" style="flex: 1;" placeholder="例如: -10012345678 或 12345678">
            <div v-if="parsedChatIds.length > 0" style="flex: 1; display: flex; flex-wrap: wrap; gap: 6px; align-items: center;">
              <span v-for="(id, idx) in parsedChatIds" :key="idx" class="id-tag" @click="removeChatId(idx)">{{ id }} ×</span>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 消息范围 -->
      <div style="margin-top: 15px; padding: 15px; border: 1px solid var(--border); border-radius: 8px;">
        <label class="form-checkbox" style="margin-bottom: 0;">
          <input type="checkbox" v-model="enableMessageRange">
          <span style="font-weight: 600;">📊 消息范围</span>
        </label>
        <div v-if="enableMessageRange" style="margin-top: 12px;">
          <p style="color: #666; margin-bottom: 8px; font-size: 13px;">支持精确范围，例如 <strong>1354-1354</strong> 只导出单条消息；<strong>1-0</strong> 表示从第 1 条到最新</p>
          <div style="display: flex; gap: 15px; align-items: center;">
            <input v-model.number="options.message_from" type="number" class="form-input" style="width: 120px;" placeholder="起始" min="1">
            <span>-</span>
            <input v-model.number="options.message_to" type="number" class="form-input" style="width: 120px;" placeholder="结束(0=最新)" min="0">
          </div>
        </div>
      </div>
      
      <!-- 消息过滤 -->
      <div style="margin-top: 15px; padding: 15px; border: 1px solid var(--border); border-radius: 8px;">
        <label class="form-checkbox" style="margin-bottom: 0;">
          <input type="checkbox" v-model="enableMessageFilter">
          <span style="font-weight: 600;">🎯 过滤消息</span>
        </label>
        <div v-if="enableMessageFilter" style="margin-top: 12px;">
          <p style="color: #666; margin-bottom: 8px; font-size: 13px;">TG 链接: https://t.me/c/<strong>群组ID</strong>/<strong>消息ID</strong></p>
          <div style="display: flex; gap: 20px; margin-bottom: 12px;">
            <label class="form-checkbox">
              <input type="radio" v-model="options.filter_mode" value="skip">
              <span>跳过指定消息</span>
            </label>
            <label class="form-checkbox">
              <input type="radio" v-model="options.filter_mode" value="specify">
              <span>只下载指定消息</span>
            </label>
          </div>
          <div style="display: flex; gap: 15px;">
            <textarea v-model="filterMessagesInput" @input="parseFilterMessages" class="form-input" rows="4" style="flex: 1; resize: vertical;" placeholder="粘贴消息 ID 或链接，自动识别数字&#10;例如: 669, https://t.me/c/123/670"></textarea>
            <div v-if="parsedMessageIds.length > 0" style="flex: 1; max-height: 120px; overflow-y: auto; display: flex; flex-wrap: wrap; gap: 6px; align-content: flex-start;">
              <span v-for="(id, idx) in parsedMessageIds" :key="idx" class="id-tag" @click="removeMessageId(idx)">{{ id }} ×</span>
            </div>
          </div>
          <p style="color: #888; font-size: 12px; margin-top: 8px;">💡 文件名格式: 消息ID-群ID-文件名</p>
        </div>
      </div>
      
      <div style="margin-top: 20px; display: flex; justify-content: space-between;">
        <router-link to="/dashboard" class="btn btn-outline">← 返回首页</router-link>
        <button @click="step = 2" class="btn btn-primary">下一步 →</button>
      </div>
    </div>
    
    <!-- 步骤 2: 媒体类型 -->
    <div v-if="step === 2" class="card">
      <div class="card-header">
        <h2>媒体文件导出设置</h2>
      </div>
      
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.photos">
          <span>🖼️ 图片</span>
        </label>
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.videos">
          <span>🎬 视频文件</span>
        </label>
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.voice_messages">
          <span>🎤 语音消息</span>
        </label>
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.video_messages">
          <span>📹 视频消息</span>
        </label>
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.stickers">
          <span>🎨 贴纸</span>
        </label>
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.gifs">
          <span>🎞️ GIF 动态图</span>
        </label>
        <label class="form-checkbox">
          <input type="checkbox" v-model="options.files">
          <span>📎 文件</span>
        </label>
      </div>
      
      <p style="margin-top: 15px; color: #666; font-size: 14px;">
        ℹ️ 不限制文件大小，将下载所有选中类型的媒体
      </p>
      
      <div style="margin-top: 20px; display: flex; justify-content: space-between;">
        <button @click="step = 1" class="btn btn-outline">← 上一步</button>
        <button @click="step = 3" class="btn btn-primary">下一步 →</button>
      </div>
    </div>
    
    <!-- 步骤 3: 其他选项 -->
    <div v-if="step === 3" class="card">
      <div class="card-header">
        <h2>其他选项</h2>
      </div>
      
      <div class="form-group">
        <label class="form-label">时间范围 (可选)</label>
        <div style="display: flex; gap: 15px;">
          <input type="date" v-model="dateFrom" class="form-input" placeholder="开始日期">
          <span style="align-self: center;">至</span>
          <input type="date" v-model="dateTo" class="form-input" placeholder="结束日期">
        </div>
      </div>
      
      <div class="form-group">
        <label class="form-label">保存路径</label>
        <input v-model="options.export_path" class="form-input" placeholder="/downloads">
      </div>
      
      <div class="form-group">
        <label class="form-label">导出格式</label>
        <div style="display: flex; gap: 20px; margin-top: 10px;">
          <label class="form-checkbox">
            <input type="radio" v-model="options.export_format" value="html">
            <span>📄 人类可读的 HTML</span>
          </label>
          <label class="form-checkbox">
            <input type="radio" v-model="options.export_format" value="json">
            <span>📋 机器可读的 JSON</span>
          </label>
          <label class="form-checkbox">
            <input type="radio" v-model="options.export_format" value="both">
            <span>📦 以上两者</span>
          </label>
        </div>
      </div>
      
      <!-- 断点续传 -->
      <div style="margin-top: 20px; padding-top: 15px; border-top: 1px solid var(--border);">
        <h3 style="margin-bottom: 10px;">断点续传</h3>
        <div style="display: flex; gap: 20px;">
          <label class="form-checkbox">
            <input type="checkbox" v-model="options.resume_download">
            <span>启用断点续传</span>
          </label>
          <label class="form-checkbox">
            <input type="checkbox" v-model="options.skip_existing">
            <span>跳过已下载的文件</span>
          </label>
        </div>
        <p style="color: #666; font-size: 13px; margin-top: 8px;">
          ℹ️ 未完成的文件使用 .downloading 后缀，下载完成后自动重命名
        </p>
      </div>
      
      <div style="margin-top: 20px; padding-top: 15px; border-top: 1px solid var(--border);">
        <h3 style="margin-bottom: 10px;">下载设置</h3>
        <div style="display: grid; grid-template-columns: 2fr 1.5fr; gap: 20px; align-items: flex-end;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label" style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
              <input type="checkbox" v-model="options.enable_parallel_chunk" style="width: 18px; height: 18px;">
              <span style="font-weight: 600;">⚡ 启用分块分块下载 (实验性)</span>
            </label>
            <p style="color: #666; font-size: 12px; margin-top: 4px; margin-left: 26px;">
              通过多连接极速下载大文件。注意：可能会增加被 Telegram 暂时限制的风险。
            </p>
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">最大并发下载数</label>
            <input v-model.number="options.max_concurrent_downloads" type="number" class="form-input" min="1" max="20">
            <p style="color: #666; font-size: 12px; margin-top: 4px;">建议范围: 5 - 10</p>
          </div>
        </div>
        
        <!-- 代理设置 -->
        <div style="margin-top: 15px;">
          <div class="form-group" style="margin-bottom: 0;">
            <label class="form-label">🌐 代理设置</label>
            <input v-model="options.proxy" class="form-input" placeholder="例如: socks5://localhost:1080">
            <p style="color: #666; font-size: 12px; margin-top: 4px;">支持 socks5/http/https 协议，格式: protocol://host:port</p>
          </div>
        </div>
      </div>
      
      <div style="margin-top: 20px; display: flex; justify-content: space-between;">
        <button @click="step = 2" class="btn btn-outline">← 上一步</button>
        <button @click="step = 4" class="btn btn-primary">下一步 →</button>
      </div>
    </div>
    
    <!-- 步骤 4: 确认 -->
    <div v-if="step === 4" class="card">
      <div class="card-header">
        <h2>确认导出</h2>
      </div>
      
      <div class="form-group">
        <label class="form-label">任务名称</label>
        <input v-model="taskName" class="form-input" placeholder="例如: 频道备份 2024-01">
      </div>
      
      <h3 style="margin: 20px 0 10px;">导出摘要</h3>
      <table class="table">
        <tr>
          <td><strong>聊天类型</strong></td>
          <td>{{ getSummaryText('chats') }}</td>
        </tr>
        <tr>
          <td><strong>媒体类型</strong></td>
          <td>{{ getSummaryText('media') }}</td>
        </tr>
        <tr>
          <td><strong>导出格式</strong></td>
          <td>{{ formatText[options.export_format] }}</td>
        </tr>
        <tr>
          <td><strong>保存路径</strong></td>
          <td>{{ options.export_path }}</td>
        </tr>
      </table>
      
      <div v-if="error" style="color: var(--danger); margin-top: 15px;">
        {{ error }}
      </div>
      
      <div style="margin-top: 20px; display: flex; justify-content: space-between;">
        <button @click="step = 3" class="btn btn-outline">← 上一步</button>
        <button @click="startExport" class="btn btn-success" :disabled="loading">
          {{ loading ? '创建中...' : '🚀 开始导出' }}
        </button>
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
const exactMessageLinkInput = ref('')
const exactMessageId = ref(null)
const exactChatId = ref(null)
const exactChatTitle = ref('')
const dateFrom = ref('')
const dateTo = ref('')

// 启用开关
const enableSpecificChats = ref(false)
const enableMessageRange = ref(false)
const enableMessageFilter = ref(false)
const exportMode = ref('quick')

// 解析后的 ID 列表
const parsedChatIds = ref([])
const parsedMessageIds = ref([])

// 智能解析: 聊天 ID 可提取所有数字；消息过滤只提取消息 ID（优先取 t.me/c 链接最后一段）
function parseNumbers(text) {
  const matches = text.match(/-?\d+/g)
  return matches ? [...new Set(matches.map(n => parseInt(n)))].filter(n => !isNaN(n)) : []
}

function parseMessageIds(text) {
  const ids = []
  const seen = new Set()

  // 1) 优先解析 Telegram 消息链接，只取最后一段消息 ID，避免把群组 ID 当成消息 ID
  const tgLinkRegex = /https?:\/\/t\.me\/(?:c\/\d+\/|[A-Za-z0-9_]+\/)(\d+)/g
  let m
  while ((m = tgLinkRegex.exec(text)) !== null) {
    const id = parseInt(m[1], 10)
    if (!isNaN(id) && id > 0 && !seen.has(id)) {
      seen.add(id)
      ids.push(id)
    }
  }

  // 2) 再解析纯数字/逗号/空格/换行输入；如果某一行包含 t.me 链接，则跳过该行的数字兜底，避免误收群组 ID
  const lines = text.split(/\r?\n/)
  for (const line of lines) {
    if (/https?:\/\/t\.me\//.test(line)) continue
    const nums = line.match(/\b\d+\b/g) || []
    for (const raw of nums) {
      const id = parseInt(raw, 10)
      if (!isNaN(id) && id > 0 && !seen.has(id)) {
        seen.add(id)
        ids.push(id)
      }
    }
  }

  return ids
}

async function resolveExactChatTitle(chatId) {
  try {
    const res = await axios.get('/api/telegram/dialogs', { headers: getAuthHeader() })
    const hit = (res.data || []).find(c => c.id === chatId)
    exactChatTitle.value = hit?.title || ''
  } catch (err) {
    console.error('获取频道名称失败:', err)
    exactChatTitle.value = ''
  }
}

function parseSpecificChats() {
  parsedChatIds.value = parseNumbers(specificChatsInput.value)
}

function parseFilterMessages() {
  parsedMessageIds.value = parseMessageIds(filterMessagesInput.value)
}

function removeChatId(idx) {
  parsedChatIds.value.splice(idx, 1)
}

function removeMessageId(idx) {
  parsedMessageIds.value.splice(idx, 1)
}

function applyExactMessageLink() {
  const text = exactMessageLinkInput.value.trim()
  if (!text) {
    showInlineError('请先粘贴 Telegram 消息链接')
    return
  }

  const m = text.match(/https?:\/\/t\.me\/c\/(\d+)\/(\d+)/)
  if (!m) {
    showInlineError('目前只支持 https://t.me/c/<群组ID>/<消息ID> 这种链接')
    return
  }

  const rawChatId = parseInt(m[1], 10)
  const messageId = parseInt(m[2], 10)
  if (isNaN(rawChatId) || isNaN(messageId) || messageId <= 0) {
    showInlineError('链接解析失败，请检查后重试')
    return
  }

  const chatId = parseInt(`-100${rawChatId}`, 10)
  exactChatId.value = chatId
  exactChatTitle.value = ''
  exactMessageId.value = messageId
  enableSpecificChats.value = true
  enableMessageRange.value = true
  specificChatsInput.value = String(chatId)
  parsedChatIds.value = [chatId]
  options.message_from = messageId
  options.message_to = messageId
  exactMessageLinkInput.value = text

  // 快速模式下默认只下载文件，减少误操作
  options.photos = false
  options.videos = false
  options.voice_messages = false
  options.video_messages = false
  options.stickers = false
  options.gifs = false
  options.files = true

  // 自动生成一个顺手的任务名
  taskName.value = `tg-${rawChatId}-${messageId}`
  error.value = ''
  resolveExactChatTitle(chatId)
}

function applyBatchPreset(mode) {
  if (!exactChatId.value || !exactMessageId.value) {
    showInlineError('请先粘贴并应用消息链接')
    return
  }

  enableSpecificChats.value = true
  enableMessageRange.value = true
  specificChatsInput.value = String(exactChatId.value)
  parsedChatIds.value = [exactChatId.value]

  if (mode === 'single') {
    options.message_from = exactMessageId.value
    options.message_to = exactMessageId.value
  } else if (mode === 'forward') {
    options.message_from = exactMessageId.value
    options.message_to = 0
  } else if (mode === 'backward') {
    options.message_from = 1
    options.message_to = exactMessageId.value
  } else if (mode === 'window100') {
    options.message_from = Math.max(1, exactMessageId.value - 50)
    options.message_to = exactMessageId.value + 50
  }

  error.value = ''
}

function showInlineError(msg) {
  error.value = msg
  setTimeout(() => {
    if (error.value === msg) error.value = ''
  }, 4000)
}

const options = reactive({
  // 聊天类型
  private_chats: true,
  bot_chats: false,
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
  parallel_chunk_connections: 3,
  enable_parallel_chunk: false,
  download_speed_limit: 0,
  
  // 消息过滤
  filter_mode: 'skip',
  filter_messages: [],
  
  // 代理设置
  proxy: ''
})

const formatText = {
  html: '人类可读的 HTML',
  json: '机器可读的 JSON',
  both: 'HTML + JSON'
}

function getSummaryText(type) {
  if (type === 'chats') {
    const items = []
    if (options.private_chats) items.push('私聊')
    if (options.bot_chats) items.push('机器人')
    if (options.private_groups) items.push('私密群组')
    if (options.private_channels) items.push('私密频道')
    if (options.public_groups) items.push('公开群组')
    if (options.public_channels) items.push('公开频道')
    return items.join(', ') || '无'
  }
  if (type === 'media') {
    const items = []
    if (options.photos) items.push('图片')
    if (options.videos) items.push('视频')
    if (options.voice_messages) items.push('语音')
    if (options.video_messages) items.push('视频消息')
    if (options.stickers) items.push('贴纸')
    if (options.gifs) items.push('GIF')
    if (options.files) items.push('文件')
    return items.join(', ') || '无'
  }
  return ''
}

async function quickStartFromLink() {
  if (!exactChatId.value || !exactMessageId.value) {
    showInlineError('请先粘贴并应用消息链接')
    return
  }
  if (!taskName.value) {
    taskName.value = `tg-${String(exactChatId.value).replace('-100', '')}-${exactMessageId.value}`
  }
  step.value = 4
  await startExport()
}

async function startExport() {
  if (!taskName.value) {
    error.value = '请输入任务名称'
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
    } else {
      // 精确单条消息范围（如 1354-1354）应原样提交
      if (!options.message_from || options.message_from < 1) {
        options.message_from = 1
      }
      if (options.message_to == null || options.message_to < 0) {
        options.message_to = 0
      }
      if (options.message_to > 0 && options.message_to < options.message_from) {
        error.value = '消息范围无效：结束消息 ID 不能小于起始消息 ID'
        loading.value = false
        return
      }
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
    
    // 跳转到任务详情监控页面
    router.push(`/tasks/${createRes.data.id}`)
  } catch (err) {
    error.value = err.response?.data?.detail || '创建任务失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.step {
  padding: 10px 20px;
  background: var(--border);
  border-radius: 20px;
  color: #666;
  font-size: 14px;
}

.step.active {
  background: var(--primary);
  color: white;
}

.id-tag {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  background: var(--primary);
  color: white;
  border-radius: 12px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.id-tag:hover {
  background: var(--danger);
}
</style>
