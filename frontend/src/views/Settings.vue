<template>
  <div class="fade-in">
    <h1 style="margin-bottom: 20px;">⚙️ 设置</h1>
    
    <!-- Telegram App API 配置 -->
    <div class="card">
      <div class="card-header">
        <h2>🔗 Telegram App API</h2>
      </div>
      
      <p style="color: #666; margin-bottom: 15px;">
        从 <a href="https://my.telegram.org/apps" target="_blank" style="color: var(--primary);">my.telegram.org</a> 获取应用 API 凭证（仅需配置一次）
      </p>
      
      <div style="display: flex; gap: 15px; align-items: flex-end;">
        <div class="form-group" style="flex: 1; margin-bottom: 0;">
          <label class="form-label">API ID</label>
          <input v-model="apiId" type="number" class="form-input" placeholder="例如: 12345678" :disabled="hasApiConfig && !editingApi">
        </div>
        <div class="form-group" style="flex: 2; margin-bottom: 0;">
          <label class="form-label">API Hash</label>
          <input v-model="apiHash" type="text" class="form-input" :placeholder="hasApiConfig && !editingApi ? '******' : '例如: abcdef1234567890...'" :disabled="hasApiConfig && !editingApi">
        </div>
        
        <div style="display: flex; gap: 10px;">
          <button v-if="!hasApiConfig || editingApi" @click="initTelegram" class="btn btn-primary" :disabled="!apiId || (!apiHash && !hasApiConfig) || loading" style="white-space: nowrap;">
            {{ loading ? '保存中...' : '保存配置' }}
          </button>
          <button v-if="hasApiConfig && !editingApi" @click="editingApi = true" class="btn btn-outline" style="white-space: nowrap;">
            修改配置
          </button>
          <button v-if="editingApi" @click="cancelEditApi" class="btn btn-outline" style="white-space: nowrap;">
            取消
          </button>
        </div>
      </div>
      
      <div v-if="hasApiConfig && !editingApi" style="margin-top: 10px; color: #28a745; font-size: 13px;">
        ✅ API 已保存至服务器 (环境变量)
      </div>
    </div>
    
    <!-- Telegram 账号登录 -->
    <div class="card">
      <div class="card-header">
        <h2>📱 Telegram 账号登录</h2>
      </div>
      
      <!-- 已连接状态 -->
      <div v-if="telegramStatus.authorized">
        <div style="display: flex; align-items: center; gap: 15px; padding: 15px; background: #d4edda; border-radius: 8px; margin-bottom: 15px;">
          <div style="width: 50px; height: 50px; background: var(--primary); border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; font-size: 24px;">
            {{ telegramStatus.user?.first_name?.[0] || '?' }}
          </div>
          <div style="flex: 1;">
            <div style="font-weight: 600; font-size: 16px;">{{ telegramStatus.user?.first_name }} {{ telegramStatus.user?.last_name }}</div>
            <div style="color: #666;">@{{ telegramStatus.user?.username || 'N/A' }}</div>
            <div style="color: #999; font-size: 12px;">ID: {{ telegramStatus.user?.id }}</div>
          </div>
          <span class="status-badge status-completed">已连接</span>
        </div>
        <button @click="disconnectTelegram" class="btn btn-outline" style="color: var(--danger); border-color: var(--danger);">
          🚪 断开连接
        </button>
      </div>
      
      <!-- 未连接 - 登录流程 -->
      <div v-else>
        <!-- 步骤指示器 -->
        <div style="display: flex; gap: 10px; margin-bottom: 20px;">
          <div :class="['login-step', loginStep >= 1 ? 'active' : '']">1. 手机号</div>
          <div :class="['login-step', loginStep >= 2 ? 'active' : '']">2. 验证码</div>
          <div :class="['login-step', loginStep >= 3 ? 'active' : '']">3. 二次验证</div>
          <div :class="['login-step', loginStep >= 4 ? 'active' : '']">4. 完成</div>
        </div>
        
        <!-- 步骤 1: 手机号 -->
        <div v-if="loginStep === 1">
          <p style="color: #666; margin-bottom: 15px;">
            输入您的 Telegram 手机号码（含国际区号）
          </p>
          <div class="form-group">
            <label class="form-label">手机号码</label>
            <input v-model="phone" type="tel" class="form-input" placeholder="+86 138xxxxxxxx">
          </div>
          <button @click="sendCode" class="btn btn-primary" :disabled="!phone || loading">
            {{ loading ? '发送中...' : '发送验证码' }}
          </button>
        </div>
        
        <!-- 步骤 2: 验证码 -->
        <div v-if="loginStep === 2">
          <p style="color: #666; margin-bottom: 15px;">
            验证码已发送到您的 Telegram 应用，请查收
          </p>
          <div class="form-group">
            <label class="form-label">验证码</label>
            <input v-model="code" type="text" class="form-input" placeholder="输入5位验证码" maxlength="5">
          </div>
          <div style="display: flex; gap: 10px;">
            <button @click="loginStep = 1" class="btn btn-outline">← 上一步</button>
            <button @click="signIn" class="btn btn-primary" :disabled="!code || loading">
              {{ loading ? '验证中...' : '验证登录' }}
            </button>
          </div>
        </div>
        
        <!-- 步骤 3: 两步验证密码 -->
        <div v-if="loginStep === 3">
          <p style="color: #666; margin-bottom: 15px;">
            您的账号已启用两步验证，请输入密码
          </p>
          <div class="form-group">
            <label class="form-label">两步验证密码</label>
            <input v-model="password" type="password" class="form-input" placeholder="输入两步验证密码" @keyup.enter="signIn">
          </div>
          <div style="display: flex; gap: 10px;">
            <button @click="loginStep = 2" class="btn btn-outline">← 上一步</button>
            <button @click="signIn" class="btn btn-primary" :disabled="!password || loading">
              {{ loading ? '验证中...' : '确认登录' }}
            </button>
          </div>
        </div>
      </div>
      
      <!-- 消息提示 -->
      <div v-if="message" :style="{ color: messageType === 'error' ? 'var(--danger)' : 'var(--success)', marginTop: '15px', padding: '10px', borderRadius: '6px', background: messageType === 'error' ? '#fee' : '#efe' }">
        {{ message }}
      </div>
    </div>
    
    <!-- Bot 配置 (可选) -->
    <div class="card">
      <div class="card-header">
        <h2>🤖 Bot 配置 (可选)</h2>
        <span v-if="botSaved" class="status-badge status-completed">已配置</span>
      </div>
      
      <p style="color: #666; margin-bottom: 15px;">
        配置 Bot Token 后可以通过 Telegram Bot 控制导出任务。
        <a href="https://t.me/BotFather" target="_blank" style="color: var(--primary);">从 @BotFather 获取</a>
      </p>
      
      <div class="form-group">
        <label class="form-label">Bot Token</label>
        <input v-model="botToken" type="text" class="form-input" placeholder="例如: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz">
      </div>
      
      <button @click="saveBotToken" class="btn btn-primary" :disabled="!botToken || savingBot">
        {{ savingBot ? '保存中...' : '保存' }}
      </button>
    </div>
    
    <!-- 导出设置 -->
    <div class="card">
      <div class="card-header">
        <h2>📁 导出设置</h2>
      </div>
      
      <div class="form-group">
        <label class="form-label">默认导出路径</label>
        <input v-model="exportPath" type="text" class="form-input" placeholder="/downloads">
      </div>
      
      <div class="form-group">
        <label class="form-label">最大并发下载数</label>
        <input v-model="maxConcurrent" type="number" class="form-input" min="1" max="10">
      </div>
      
      <button @click="saveSettings" class="btn btn-primary">保存设置</button>
    </div>

    <!-- 版本信息 -->
    <div style="text-align: center; margin-top: 30px; color: #999; font-size: 12px; padding-bottom: 20px;">
      <p>TG Export v1.1.3</p>
      <p>© 2024 TG Export Team</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import axios from 'axios'

const apiId = ref('')
const apiHash = ref('')
const phone = ref('')
const code = ref('')
const password = ref('')
const phoneCodeHash = ref('')
const botToken = ref('')
const exportPath = ref('/downloads')
const maxConcurrent = ref(5)
const editingApi = ref(false)

const telegramStatus = ref({ authorized: false, user: null })
const loginStep = ref(1)
const loading = ref(false)
const message = ref('')
const messageType = ref('success')
const botSaved = ref(false)
const savingBot = ref(false)
const hasApiConfig = ref(false)  // 后端是否已配置 API

// API 是否已配置 (从后端读取的状态)
const apiConfigured = computed(() => {
  return hasApiConfig.value && !editingApi.value
})

function getAuthHeader() {
  return { Authorization: `Bearer ${localStorage.getItem('token')}` }
}

async function fetchStatus() {
  try {
    const [statusRes, settingsRes] = await Promise.all([
      axios.get('/api/telegram/status', { headers: getAuthHeader() }),
      axios.get('/api/settings', { headers: getAuthHeader() })
    ])
    telegramStatus.value = statusRes.data
    
    // 读取后端配置状态
    hasApiConfig.value = settingsRes.data.has_api_config || false
    if (settingsRes.data.api_id) {
      apiId.value = settingsRes.data.api_id
    }
    // 不主动设置 apiHash，保持为空直到用户点击修改
    
    exportPath.value = settingsRes.data.export_path || '/downloads'
    maxConcurrent.value = settingsRes.data.max_concurrent_downloads || 5
    botSaved.value = settingsRes.data.has_bot_token || false
  } catch (err) {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      router.push('/login')
    }
    console.error('获取设置失败:', err)
  }
}

function cancelEditApi() {
  editingApi.value = false
  apiHash.value = '' // 清空未保存的输入
}

async function initTelegram() {
  loading.value = true
  try {
    await axios.post(`/api/telegram/init?api_id=${apiId.value}&api_hash=${apiHash.value}`, {}, { headers: getAuthHeader() })
    editingApi.value = false
    showMessage('API 配置已保存', 'success')
  } catch (err) {
    showMessage('配置失败: ' + (err.response?.data?.detail || err.message), 'error')
  } finally {
    loading.value = false
  }
}

async function sendCode() {
  loading.value = true
  try {
    const res = await axios.post(`/api/telegram/send-code?phone=${encodeURIComponent(phone.value)}`, {}, { headers: getAuthHeader() })
    phoneCodeHash.value = res.data.phone_code_hash
    loginStep.value = 2
    showMessage('验证码已发送，请查看 Telegram 应用', 'success')
  } catch (err) {
    showMessage('发送失败: ' + (err.response?.data?.detail || err.message), 'error')
  } finally {
    loading.value = false
  }
}

async function signIn() {
  loading.value = true
  try {
    await axios.post('/api/telegram/sign-in', null, {
      headers: getAuthHeader(),
      params: {
        phone: phone.value,
        code: code.value,
        phone_code_hash: phoneCodeHash.value,
        password: password.value || undefined
      }
    })
    showMessage('🎉 登录成功!', 'success')
    loginStep.value = 4
    await fetchStatus()
  } catch (err) {
    const detail = err.response?.data?.detail || err.message
    // 监听 403 (专门给 2FA 准备) 或 401 (带 2FA 提示)
    if ((err.response?.status === 403 || err.response?.status === 401) && 
        (detail === 'SESSION_PASSWORD_NEEDED' || detail.includes('2FA') || detail.includes('password'))) {
      loginStep.value = 3  // 跳转至两步验证
      showMessage('请提供两步验证密码 (Cloud Password)', 'success')
    } else {
      showMessage('登录失败: ' + detail, 'error')
    }
  } finally {
    loading.value = false
  }
}

async function disconnectTelegram() {
  if (!confirm('确定要断开 Telegram 连接吗？')) return
  
  try {
    await axios.post('/api/telegram/disconnect', {}, { headers: getAuthHeader() })
    telegramStatus.value = { authorized: false, user: null }
    loginStep.value = 1
    showMessage('已断开连接', 'success')
  } catch (err) {
    showMessage('断开失败: ' + (err.response?.data?.detail || err.message), 'error')
  }
}

async function saveBotToken() {
  savingBot.value = true
  try {
    await axios.post(`/api/settings/bot-token?token=${encodeURIComponent(botToken.value)}`, {}, { headers: getAuthHeader() })
    botSaved.value = true
    showMessage('Bot Token 已保存', 'success')
  } catch (err) {
    showMessage('保存失败: ' + (err.response?.data?.detail || err.message), 'error')
  } finally {
    savingBot.value = false
  }
}

async function saveSettings() {
  try {
    await axios.post('/api/settings', {
      export_path: exportPath.value,
      max_concurrent_downloads: maxConcurrent.value
    }, { headers: getAuthHeader() })
    showMessage('设置已保存', 'success')
  } catch (err) {
    showMessage('保存失败: ' + (err.response?.data?.detail || err.message), 'error')
  }
}

function showMessage(msg, type) {
  message.value = msg
  messageType.value = type
  setTimeout(() => { message.value = '' }, 5000)
}

onMounted(fetchStatus)
</script>

<style scoped>
.login-step {
  padding: 8px 16px;
  background: var(--border);
  border-radius: 20px;
  color: #666;
  font-size: 13px;
  white-space: nowrap;
}

.login-step.active {
  background: var(--primary);
  color: white;
}
</style>
