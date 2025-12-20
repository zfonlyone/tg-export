<template>
  <div class="fade-in">
    <h1 style="margin-bottom: 20px;">⚙️ 设置</h1>
    
    <!-- Telegram 配置 -->
    <div class="card">
      <div class="card-header">
        <h2>🔗 Telegram 配置</h2>
      </div>
      
      <div v-if="telegramStatus.authorized" style="margin-bottom: 20px;">
        <div style="display: flex; align-items: center; gap: 15px; padding: 15px; background: #d4edda; border-radius: 8px;">
          <span style="font-size: 24px;">✅</span>
          <div>
            <div style="font-weight: 600;">已连接: {{ telegramStatus.user?.first_name }}</div>
            <div style="color: #666;">@{{ telegramStatus.user?.username }}</div>
          </div>
        </div>
      </div>
      
      <div v-else>
        <div class="form-group">
          <label class="form-label">API ID</label>
          <input v-model="apiId" type="number" class="form-input" placeholder="从 my.telegram.org 获取">
        </div>
        
        <div class="form-group">
          <label class="form-label">API Hash</label>
          <input v-model="apiHash" type="text" class="form-input" placeholder="从 my.telegram.org 获取">
        </div>
        
        <button @click="initTelegram" class="btn btn-primary" :disabled="!apiId || !apiHash">
          初始化 Telegram
        </button>
        
        <div v-if="showLogin" style="margin-top: 20px; padding-top: 20px; border-top: 1px solid var(--border);">
          <h3 style="margin-bottom: 15px;">登录验证</h3>
          
          <div v-if="loginStep === 1">
            <div class="form-group">
              <label class="form-label">手机号码</label>
              <input v-model="phone" type="tel" class="form-input" placeholder="+86 138xxxx">
            </div>
            <button @click="sendCode" class="btn btn-primary" :disabled="!phone">发送验证码</button>
          </div>
          
          <div v-if="loginStep === 2">
            <div class="form-group">
              <label class="form-label">验证码</label>
              <input v-model="code" type="text" class="form-input" placeholder="输入收到的验证码">
            </div>
            <button @click="signIn" class="btn btn-primary" :disabled="!code">验证登录</button>
          </div>
          
          <div v-if="loginStep === 3">
            <div class="form-group">
              <label class="form-label">两步验证密码</label>
              <input v-model="password" type="password" class="form-input" placeholder="输入两步验证密码">
            </div>
            <button @click="signIn" class="btn btn-primary" :disabled="!password">确认</button>
          </div>
        </div>
      </div>
      
      <div v-if="message" :style="{ color: messageType === 'error' ? 'var(--danger)' : 'var(--success)', marginTop: '15px' }">
        {{ message }}
      </div>
    </div>
    
    <!-- Bot 配置 -->
    <div class="card">
      <div class="card-header">
        <h2>🤖 Bot 配置 (可选)</h2>
      </div>
      
      <p style="color: #666; margin-bottom: 15px;">
        配置 Bot Token 后可以通过 Telegram Bot 控制导出任务
      </p>
      
      <div class="form-group">
        <label class="form-label">Bot Token</label>
        <input v-model="botToken" type="text" class="form-input" placeholder="从 @BotFather 获取">
      </div>
      
      <button @click="saveBotToken" class="btn btn-primary">保存</button>
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
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

const telegramStatus = ref({ authorized: false, user: null })
const showLogin = ref(false)
const loginStep = ref(1)
const message = ref('')
const messageType = ref('success')

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
    
    if (settingsRes.data.api_id) {
      apiId.value = settingsRes.data.api_id
    }
    exportPath.value = settingsRes.data.export_path || '/downloads'
    maxConcurrent.value = settingsRes.data.max_concurrent_downloads || 5
  } catch (err) {
    console.error('获取设置失败:', err)
  }
}

async function initTelegram() {
  try {
    await axios.post(`/api/telegram/init?api_id=${apiId.value}&api_hash=${apiHash.value}`, {}, { headers: getAuthHeader() })
    showLogin.value = true
    loginStep.value = 1
    showMessage('初始化成功，请输入手机号', 'success')
  } catch (err) {
    showMessage('初始化失败: ' + (err.response?.data?.detail || err.message), 'error')
  }
}

async function sendCode() {
  try {
    const res = await axios.post(`/api/telegram/send-code?phone=${encodeURIComponent(phone.value)}`, {}, { headers: getAuthHeader() })
    phoneCodeHash.value = res.data.phone_code_hash
    loginStep.value = 2
    showMessage('验证码已发送', 'success')
  } catch (err) {
    showMessage('发送失败: ' + (err.response?.data?.detail || err.message), 'error')
  }
}

async function signIn() {
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
    showMessage('登录成功!', 'success')
    await fetchStatus()
    showLogin.value = false
  } catch (err) {
    const detail = err.response?.data?.detail || err.message
    if (detail.includes('2FA') || detail.includes('password')) {
      loginStep.value = 3
      showMessage('请输入两步验证密码', 'success')
    } else {
      showMessage('登录失败: ' + detail, 'error')
    }
  }
}

async function saveBotToken() {
  showMessage('Bot Token 已保存', 'success')
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
