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
      
      <!-- 指定聊天 -->
      <div style="margin-top: 20px;">
        <h3 style="margin-bottom: 10px;">指定聊天 (可选)</h3>
        <p style="color: #666; margin-bottom: 10px; font-size: 14px;">
          输入聊天 ID，多个用逗号分隔。留空则导出所有符合条件的聊天。
        </p>
        <input 
          v-model="specificChatsInput" 
          class="form-input" 
          placeholder="例如: -1001234567890, -1009876543210"
        >
      </div>
      
      <!-- 消息范围 -->
      <div style="margin-top: 20px;">
        <h3 style="margin-bottom: 10px;">消息范围 (可选)</h3>
        <p style="color: #666; margin-bottom: 10px; font-size: 14px;">
          指定导出的消息 ID 范围。“1-0” 表示从第1条到最新，“1-100” 表示第1条到第100条。
        </p>
        <div style="display: flex; gap: 15px; align-items: center;">
          <input 
            v-model.number="options.message_from" 
            type="number" 
            class="form-input" 
            style="width: 120px;"
            placeholder="起始 ID"
            min="1"
          >
          <span>-</span>
          <input 
            v-model.number="options.message_to" 
            type="number" 
            class="form-input" 
            style="width: 120px;"
            placeholder="结束 ID (0=最新)"
            min="0"
          >
        </div>
      </div>
      
      <div style="margin-top: 20px; text-align: right;">
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
const dateFrom = ref('')
const dateTo = ref('')

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
  export_format: 'html'
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

async function startExport() {
  if (!taskName.value) {
    error.value = '请输入任务名称'
    return
  }
  
  loading.value = true
  error.value = ''
  
  try {
    // 处理指定聊天
    if (specificChatsInput.value) {
      options.specific_chats = specificChatsInput.value
        .split(',')
        .map(s => parseInt(s.trim()))
        .filter(n => !isNaN(n))
    }
    
    // 处理日期
    if (dateFrom.value) {
      options.date_from = new Date(dateFrom.value).toISOString()
    }
    if (dateTo.value) {
      options.date_to = new Date(dateTo.value).toISOString()
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
    
    // 跳转到任务页面
    router.push('/tasks')
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
</style>
