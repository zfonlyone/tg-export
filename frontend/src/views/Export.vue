<template>
  <div class="fade-in export-page">
    <div class="page-header export-header">
      <div>
        <h1>📥 导出数据</h1>
        <p class="subtitle">面向桌面与移动端重排的导出配置流程，适合快速下载，也适合精细历史归档。</p>
      </div>
      <div class="header-actions">
        <router-link to="/dashboard" class="btn btn-outline">← 返回首页</router-link>
        <button class="btn btn-outline" @click="resetToQuickMode">重置</button>
      </div>
    </div>

    <div class="export-shell">
      <aside class="summary-rail card">
        <div class="rail-header">
          <div>
            <div class="eyebrow">导出方案</div>
            <h3>{{ currentStepLabel }}</h3>
          </div>
          <span class="mode-badge" :class="exportMode">{{ exportMode === 'quick' ? '⚡ 快速模式' : '🛠️ 高级模式' }}</span>
        </div>

        <div class="stepper-mobile card">
          <div class="stepper-scroll">
            <button
              v-for="item in steps"
              :key="item.id"
              class="step-chip"
              :class="{ active: step === item.id, done: step > item.id }"
              @click="step = item.id"
            >
              <span class="step-index">{{ item.id }}</span>
              <span>{{ item.label }}</span>
            </button>
          </div>
        </div>

        <div class="summary-card card compact-card">
          <div class="summary-title-row">
            <h4>当前摘要</h4>
            <span class="summary-pill">{{ exportIntentLabel }}</span>
          </div>
          <div class="summary-list">
            <div class="summary-item">
              <span class="label">聊天范围</span>
              <span class="value">{{ summaryChatScope }}</span>
            </div>
            <div class="summary-item">
              <span class="label">消息范围</span>
              <span class="value">{{ summaryMessageRange }}</span>
            </div>
            <div class="summary-item">
              <span class="label">媒体类型</span>
              <span class="value">{{ summaryMedia }}</span>
            </div>
            <div class="summary-item">
              <span class="label">导出格式</span>
              <span class="value">{{ formatText[options.export_format] }}</span>
            </div>
          </div>
        </div>

        <div class="summary-card card compact-card" v-if="exactMessageId && exactChatId">
          <div class="summary-title-row">
            <h4>🎯 精确消息目标</h4>
            <span class="mini-muted">单条下载捷径</span>
          </div>
          <div class="exact-preview-grid">
            <div class="summary-item">
              <span class="label">聊天</span>
              <span class="value">{{ exactChatTitle || exactChatId }}</span>
            </div>
            <div class="summary-item">
              <span class="label">消息 ID</span>
              <span class="value">#{{ exactMessageId }}</span>
            </div>
            <div class="summary-item" v-if="exactMessagePreview?.media_type">
              <span class="label">媒体类型</span>
              <span class="value">{{ exactMessagePreview.media_type }}</span>
            </div>
            <div class="summary-item" v-if="exactMessagePreview?.file_size">
              <span class="label">大小</span>
              <span class="value">{{ formatBytes(exactMessagePreview.file_size) }}</span>
            </div>
          </div>
          <div v-if="exactMessagePreview?.text || exactMessagePreview?.caption" class="preview-bubble">
            {{ exactMessagePreview.caption || exactMessagePreview.text }}
          </div>
        </div>

        <div v-if="error" class="error-callout">
          {{ error }}
        </div>
      </aside>

      <section class="export-main">
        <div class="stepper-desktop card">
          <div class="stepper-row">
            <button
              v-for="item in steps"
              :key="item.id"
              class="step-panel"
              :class="{ active: step === item.id, done: step > item.id }"
              @click="step = item.id"
            >
              <span class="num">{{ item.id }}</span>
              <span class="label">{{ item.label }}</span>
            </button>
          </div>
        </div>

        <div v-if="step === 1" class="step-layout">
          <div class="card hero-card">
            <div class="hero-top">
              <div>
                <div class="eyebrow">历史记录导出设置</div>
                <h2>先决定导出范围</h2>
                <p class="helper-text">快速模式适合“拿到链接就开始下”，高级模式适合长期归档、跨频道导出和复杂过滤。</p>
              </div>
              <div class="mode-switch">
                <button class="switch-btn" :class="{ active: exportMode === 'quick' }" @click="setExportMode('quick')">⚡ 快速模式</button>
                <button class="switch-btn" :class="{ active: exportMode === 'advanced' }" @click="setExportMode('advanced')">🛠️ 高级模式</button>
              </div>
            </div>

            <div class="hero-grid">
              <div class="hero-tile" :class="{ selected: exportMode === 'quick' }">
                <div class="tile-icon">⚡</div>
                <div>
                  <div class="tile-title">快速模式</div>
                  <div class="tile-desc">用消息链接直接生成任务，最适合只下载某一个文件或当前消息附近的历史。</div>
                </div>
              </div>
              <div class="hero-tile" :class="{ selected: exportMode === 'advanced' }">
                <div class="tile-icon">🛠️</div>
                <div>
                  <div class="tile-title">高级模式</div>
                  <div class="tile-desc">按聊天类型、媒体类型、时间范围、消息范围和过滤规则精细导出。</div>
                </div>
              </div>
            </div>
          </div>

          <div class="card section-card highlight-card">
            <div class="section-head">
              <div>
                <h3>🎯 精确单条消息 / 文件下载</h3>
                <p>粘贴 Telegram 消息链接，自动填充“指定聊天 + 单条消息范围”。移动端也适合直接粘贴后一步到位。</p>
              </div>
              <span class="section-badge">最快路径</span>
            </div>

            <div class="exact-link-form">
              <input v-model="exactMessageLinkInput" class="form-input large-input" placeholder="例如: https://t.me/c/3450385408/1354">
              <button @click="applyExactMessageLink" class="btn btn-primary">一键填充</button>
            </div>

            <div v-if="exactMessageId && exactChatId" class="preset-wrap">
              <div class="preset-label">批量快捷范围</div>
              <div class="preset-grid">
                <button @click="applyBatchPreset('single')" class="preset-chip">仅此消息</button>
                <button @click="applyBatchPreset('forward')" class="preset-chip">从此消息到最新</button>
                <button @click="applyBatchPreset('backward')" class="preset-chip">从 1 到此消息</button>
                <button @click="applyBatchPreset('window100')" class="preset-chip">前后各 50 条</button>
              </div>
              <div class="cta-row">
                <button @click="quickStartFromLink" class="btn btn-success">🚀 立即创建当前消息下载任务</button>
                <button @click="step = 2" class="btn btn-outline">继续微调媒体与下载设置</button>
              </div>
            </div>
          </div>

          <div v-if="exportMode === 'quick'" class="card section-card quick-mode-card">
            <div class="section-head">
              <div>
                <h3>⚡ 快速模式：更少步骤，更快开始</h3>
                <p>推荐流程是“贴链接 → 自动识别消息 → 直接创建任务”。如果不贴链接，也可以只指定单个聊天快速拉取。</p>
              </div>
              <span class="section-badge">引导式</span>
            </div>

            <div class="quick-guide-grid">
              <div class="quick-guide-tile">
                <strong>1. 贴消息链接</strong>
                <span>自动生成单消息或附近范围下载配置</span>
              </div>
              <div class="quick-guide-tile">
                <strong>2. 确认媒体类型</strong>
                <span>默认更偏向文件下载，也可在下一步微调</span>
              </div>
              <div class="quick-guide-tile">
                <strong>3. 直接创建任务</strong>
                <span>减少复杂筛选，适合移动端快速操作</span>
              </div>
            </div>

            <div class="card soft-section">
              <div class="toggle-head">
                <label class="inline-toggle">
                  <input type="checkbox" v-model="enableSpecificChats">
                  <span>
                    <strong>📌 快速指定聊天</strong>
                    <small>不走全量聊天类型筛选，只导出你输入的目标聊天。</small>
                  </span>
                </label>
              </div>
              <div v-if="enableSpecificChats" class="stack-gap">
                <input v-model="specificChatsInput" @input="parseSpecificChats" class="form-input" placeholder="例如: -10012345678 或 12345678">
                <div v-if="parsedChatIds.length > 0" class="tag-list">
                  <button v-for="(id, idx) in parsedChatIds" :key="idx" class="id-tag" @click="removeChatId(idx)">{{ id }} ×</button>
                </div>
              </div>
            </div>
          </div>

          <template v-else>
            <div class="card section-card">
              <div class="section-head">
                <div>
                  <h3>🧭 聊天范围</h3>
                  <p>高级模式下先决定自动扫描哪些对话类型，再通过消息过滤控制历史范围与精细筛选。</p>
                </div>
                <span class="section-badge">完整控制</span>
              </div>

              <div class="selection-grid">
                <label class="selection-card" :class="{ active: options.private_chats }">
                  <input type="checkbox" v-model="options.private_chats">
                  <span class="title">👤 私聊</span>
                  <span class="desc">个人聊天记录</span>
                </label>
                <label class="selection-card" :class="{ active: options.bot_chats }">
                  <input type="checkbox" v-model="options.bot_chats">
                  <span class="title">🤖 机器人对话</span>
                  <span class="desc">Bot 相关聊天</span>
                </label>
                <label class="selection-card" :class="{ active: options.private_groups }">
                  <input type="checkbox" v-model="options.private_groups">
                  <span class="title">👥 私密群组</span>
                  <span class="desc">受邀请加入的群</span>
                </label>
                <label class="selection-card" :class="{ active: options.private_channels }">
                  <input type="checkbox" v-model="options.private_channels">
                  <span class="title">📢 私密频道</span>
                  <span class="desc">私有频道历史</span>
                </label>
                <label class="selection-card" :class="{ active: options.public_groups }">
                  <input type="checkbox" v-model="options.public_groups">
                  <span class="title">🌐 公开群组</span>
                  <span class="desc">公开加入的群</span>
                </label>
                <label class="selection-card" :class="{ active: options.public_channels }">
                  <input type="checkbox" v-model="options.public_channels">
                  <span class="title">📣 公开频道</span>
                  <span class="desc">公开频道消息</span>
                </label>
              </div>

              <label class="inline-toggle soft-panel">
                <input type="checkbox" v-model="options.only_my_messages">
                <span>
                  <strong>只导出我的消息</strong>
                  <small>适合做个人发言归档，避免把整个群历史都拉下来。</small>
                </span>
              </label>
            </div>

            <div class="card section-card">
              <div class="toggle-head">
                <label class="inline-toggle">
                  <input type="checkbox" v-model="enableSpecificChats">
                  <span>
                    <strong>📌 指定聊天</strong>
                    <small>粘贴聊天 ID 或消息链接里解析出的聊天号，仅导出这些目标。</small>
                  </span>
                </label>
              </div>
              <div v-if="enableSpecificChats" class="stack-gap">
                <input v-model="specificChatsInput" @input="parseSpecificChats" class="form-input" placeholder="例如: -10012345678 或 12345678">
                <div v-if="parsedChatIds.length > 0" class="tag-list">
                  <button v-for="(id, idx) in parsedChatIds" :key="idx" class="id-tag" @click="removeChatId(idx)">{{ id }} ×</button>
                </div>
                <p class="helper-text compact">后台会尝试自动补全缺少的 `-100` 前缀。</p>
              </div>
            </div>
          </template>

          <div class="card section-card" :class="{ 'advanced-emphasis': exportMode === 'advanced' }">
            <div class="toggle-head">
              <label class="inline-toggle">
                <input type="checkbox" v-model="enableMessageFilter">
                <span>
                  <strong>🎯 消息过滤</strong>
                  <small>{{ exportMode === 'quick' ? '在快速模式里，只有需要精确范围时再打开它。' : '高级模式里，消息范围与指定/跳过消息都集中放在这里。' }}</small>
                </span>
              </label>
            </div>

            <div v-if="enableMessageFilter" class="stack-gap">
              <div class="card soft-section">
                <div class="toggle-head">
                  <label class="inline-toggle">
                    <input type="checkbox" v-model="enableMessageRange">
                    <span>
                      <strong>📊 消息范围</strong>
                      <small>支持精确范围，比如 `1354 - 1354` 仅导出单条消息。</small>
                    </span>
                  </label>
                </div>
                <div v-if="enableMessageRange" class="range-grid">
                  <div>
                    <label class="field-label">起始消息 ID</label>
                    <input v-model.number="options.message_from" type="number" class="form-input" min="1" placeholder="起始">
                  </div>
                  <div>
                    <label class="field-label">结束消息 ID</label>
                    <input v-model.number="options.message_to" type="number" class="form-input" min="0" placeholder="0 = 最新">
                  </div>
                </div>
              </div>

              <div class="radio-group">
                <label class="radio-pill" :class="{ active: options.filter_mode === 'skip' }">
                  <input type="radio" v-model="options.filter_mode" value="skip">
                  <span>跳过指定消息</span>
                </label>
                <label class="radio-pill" :class="{ active: options.filter_mode === 'specify' }">
                  <input type="radio" v-model="options.filter_mode" value="specify">
                  <span>只下载指定消息</span>
                </label>
              </div>

              <textarea v-model="filterMessagesInput" @input="parseFilterMessages" class="form-input" rows="4" placeholder="可粘贴消息 ID 或 Telegram 链接，系统会自动识别"></textarea>

              <div v-if="parsedMessageIds.length > 0" class="tag-list">
                <button v-for="(id, idx) in parsedMessageIds" :key="idx" class="id-tag" @click="removeMessageId(idx)">{{ id }} ×</button>
              </div>
            </div>
          </div>
        </div>

        <div v-if="step === 2" class="step-layout">
          <div class="card section-card">
            <div class="section-head">
              <div>
                <div class="eyebrow">媒体文件导出设置</div>
                <h2>选你真正想要的媒体类型</h2>
                <p>用卡片式筛选减少误点，也方便手机上快速选择。</p>
              </div>
              <span class="section-badge">多选</span>
            </div>

            <div class="selection-grid media-grid">
              <label class="selection-card media" :class="{ active: options.photos }">
                <input type="checkbox" v-model="options.photos">
                <span class="title">🖼️ 图片</span>
                <span class="desc">相册、截图、照片</span>
              </label>
              <label class="selection-card media" :class="{ active: options.videos }">
                <input type="checkbox" v-model="options.videos">
                <span class="title">🎬 视频文件</span>
                <span class="desc">普通视频资源</span>
              </label>
              <label class="selection-card media" :class="{ active: options.voice_messages }">
                <input type="checkbox" v-model="options.voice_messages">
                <span class="title">🎤 语音消息</span>
                <span class="desc">语音条</span>
              </label>
              <label class="selection-card media" :class="{ active: options.video_messages }">
                <input type="checkbox" v-model="options.video_messages">
                <span class="title">📹 视频消息</span>
                <span class="desc">圆形视频</span>
              </label>
              <label class="selection-card media" :class="{ active: options.stickers }">
                <input type="checkbox" v-model="options.stickers">
                <span class="title">🎨 贴纸</span>
                <span class="desc">静态或动态贴纸</span>
              </label>
              <label class="selection-card media" :class="{ active: options.gifs }">
                <input type="checkbox" v-model="options.gifs">
                <span class="title">🎞️ GIF</span>
                <span class="desc">动图与动画</span>
              </label>
              <label class="selection-card media" :class="{ active: options.files }">
                <input type="checkbox" v-model="options.files">
                <span class="title">📎 文件</span>
                <span class="desc">压缩包、文档等</span>
              </label>
            </div>
          </div>
        </div>

        <div v-if="step === 3" class="step-layout">
          <div class="card section-card">
            <div class="section-head">
              <div>
                <div class="eyebrow">其他选项</div>
                <h2>下载、格式与保存策略</h2>
                <p>这一步主要是导出格式、时间范围、断点续传和性能配置。</p>
              </div>
            </div>

            <div class="section-split uneven">
              <div class="card soft-section">
                <h4>📅 时间范围</h4>
                <p class="helper-text compact">不填则导出全部时间。适合按月份或事件区间归档。</p>
                <div class="range-grid">
                  <div>
                    <label class="field-label">开始日期</label>
                    <input type="date" v-model="dateFrom" class="form-input">
                  </div>
                  <div>
                    <label class="field-label">结束日期</label>
                    <input type="date" v-model="dateTo" class="form-input">
                  </div>
                </div>
              </div>

              <div class="card soft-section">
                <h4>📂 保存路径</h4>
                <p class="helper-text compact">默认保存到下载目录。移动端查看时也更容易理解最终落点。</p>
                <input v-model="options.export_path" class="form-input" placeholder="/downloads">
              </div>
            </div>

            <div class="card soft-section">
              <h4>📦 导出格式</h4>
              <div class="radio-grid">
                <label class="radio-card" :class="{ active: options.export_format === 'html' }">
                  <input type="radio" v-model="options.export_format" value="html">
                  <strong>📄 HTML</strong>
                  <small>更适合人直接浏览</small>
                </label>
                <label class="radio-card" :class="{ active: options.export_format === 'json' }">
                  <input type="radio" v-model="options.export_format" value="json">
                  <strong>📋 JSON</strong>
                  <small>更适合机器处理</small>
                </label>
                <label class="radio-card" :class="{ active: options.export_format === 'both' }">
                  <input type="radio" v-model="options.export_format" value="both">
                  <strong>📚 两者都要</strong>
                  <small>展示与后续处理都兼顾</small>
                </label>
              </div>
            </div>

            <div class="section-split uneven">
              <div class="card soft-section">
                <h4>♻️ 断点续传</h4>
                <div class="stack-gap">
                  <label class="inline-toggle soft-panel">
                    <input type="checkbox" v-model="options.resume_download">
                    <span>
                      <strong>启用断点续传</strong>
                      <small>网络中断后继续下载，不从头重来。</small>
                    </span>
                  </label>
                  <label class="inline-toggle soft-panel">
                    <input type="checkbox" v-model="options.skip_existing">
                    <span>
                      <strong>跳过已下载文件</strong>
                      <small>避免重复下载，提高重跑效率。</small>
                    </span>
                  </label>
                </div>
              </div>

              <div class="card soft-section">
                <h4>⚙️ 下载设置</h4>
                <div class="stack-gap">
                  <div>
                    <label class="field-label">最大并发下载数</label>
                    <input v-model.number="options.max_concurrent_downloads" type="number" class="form-input" min="1" max="20">
                    <p class="helper-text compact">建议 5 - 10，太高可能导致 Telegram 限制更频繁。</p>
                  </div>
                  <label class="inline-toggle soft-panel">
                    <input type="checkbox" v-model="options.enable_parallel_chunk">
                    <span>
                      <strong>⚡ 启用分块下载（实验性）</strong>
                      <small>更快，但也可能增加限速风险。</small>
                    </span>
                  </label>
                </div>
              </div>
            </div>

            <div class="card soft-section">
              <h4>🌐 代理设置</h4>
              <input v-model="options.proxy" class="form-input" placeholder="例如: socks5://localhost:1080">
              <p class="helper-text compact">支持 socks5/http/https，格式：`protocol://host:port`</p>
            </div>
          </div>
        </div>

        <div v-if="step === 4" class="step-layout">
          <div class="card section-card">
            <div class="section-head">
              <div>
                <div class="eyebrow">确认导出</div>
                <h2>最后确认任务信息</h2>
                <p>这里更像移动端下的“下单前确认页”，先看摘要，再正式创建任务。</p>
              </div>
            </div>

            <div class="section-split uneven">
              <div class="card soft-section">
                <h4>🏷️ 任务名称</h4>
                <input v-model="taskName" class="form-input" placeholder="例如: 频道备份 2024-01">
              </div>

              <div class="card soft-section">
                <h4>🧭 导出意图</h4>
                <div class="intent-highlight">
                  {{ exportIntentLabel }} · {{ summaryChatScope }} · {{ summaryMessageRange }}
                </div>
              </div>
            </div>

            <div class="card soft-section">
              <h4>📋 导出摘要</h4>
              <div class="summary-table">
                <div class="summary-row">
                  <span class="key">聊天类型</span>
                  <span class="val">{{ getSummaryText('chats') }}</span>
                </div>
                <div class="summary-row">
                  <span class="key">媒体类型</span>
                  <span class="val">{{ getSummaryText('media') }}</span>
                </div>
                <div class="summary-row">
                  <span class="key">导出格式</span>
                  <span class="val">{{ formatText[options.export_format] }}</span>
                </div>
                <div class="summary-row">
                  <span class="key">保存路径</span>
                  <span class="val">{{ options.export_path }}</span>
                </div>
                <div class="summary-row" v-if="options.proxy">
                  <span class="key">代理</span>
                  <span class="val">{{ options.proxy }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="action-footer card">
          <div class="footer-hint">
            <strong>第 {{ step }} 步 / 共 4 步</strong>
            <span>{{ currentStepHint }}</span>
          </div>
          <div class="footer-buttons">
            <button v-if="step > 1" @click="step -= 1" class="btn btn-outline">← 上一步</button>
            <button v-if="step < 4" @click="step += 1" class="btn btn-primary">下一步 →</button>
            <button v-if="step === 4" @click="startExport" class="btn btn-success" :disabled="loading">
              {{ loading ? '创建中...' : '🚀 开始导出' }}
            </button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
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
const exactMessagePreview = ref(null)
const dateFrom = ref('')
const dateTo = ref('')

const enableSpecificChats = ref(false)
const enableMessageRange = ref(false)
const enableMessageFilter = ref(false)
const exportMode = ref('quick')

const parsedChatIds = ref([])
const parsedMessageIds = ref([])

const steps = [
  { id: 1, label: '范围' },
  { id: 2, label: '媒体' },
  { id: 3, label: '下载设置' },
  { id: 4, label: '确认创建' }
]

function parseNumbers(text) {
  const matches = text.match(/-?\d+/g)
  return matches ? [...new Set(matches.map(n => parseInt(n)))].filter(n => !isNaN(n)) : []
}

function parseMessageIds(text) {
  const ids = []
  const seen = new Set()
  const tgLinkRegex = /https?:\/\/t\.me\/(?:c\/\d+\/|[A-Za-z0-9_]+\/)(\d+)/g
  let m
  while ((m = tgLinkRegex.exec(text)) !== null) {
    const id = parseInt(m[1], 10)
    if (!isNaN(id) && id > 0 && !seen.has(id)) {
      seen.add(id)
      ids.push(id)
    }
  }

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

function getAuthHeader() {
  return { Authorization: `Bearer ${localStorage.getItem('token')}` }
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

async function resolveExactMessagePreview(chatId, messageId) {
  try {
    const res = await axios.get('/api/telegram/message-preview', {
      headers: getAuthHeader(),
      params: { chat_id: chatId, message_id: messageId }
    })
    exactMessagePreview.value = res.data
    if (res.data?.chat?.title) exactChatTitle.value = res.data.chat.title
  } catch (err) {
    console.error('获取消息预览失败:', err)
    exactMessagePreview.value = null
  }
}

function applyQuickDefaults(chatId, messageId) {
  exportMode.value = 'quick'
  options.private_chats = false
  options.bot_chats = false
  options.private_groups = false
  options.private_channels = false
  options.public_groups = false
  options.public_channels = false
  options.only_my_messages = false

  enableSpecificChats.value = true
  enableMessageFilter.value = true
  enableMessageRange.value = true
  specificChatsInput.value = String(chatId)
  parsedChatIds.value = [chatId]
  options.message_from = messageId
  options.message_to = messageId

  options.photos = false
  options.videos = false
  options.voice_messages = false
  options.video_messages = false
  options.stickers = false
  options.gifs = false
  options.files = true

  options.filter_mode = 'specify'
  options.filter_messages = []
}

function applyModeDefaults(mode) {
  if (mode === 'quick') {
    options.private_chats = false
    options.bot_chats = false
    options.private_groups = false
    options.private_channels = false
    options.public_groups = false
    options.public_channels = false
    options.only_my_messages = false
    enableSpecificChats.value = true
    enableMessageFilter.value = false
    enableMessageRange.value = false
    if (!taskName.value) taskName.value = '快速导出任务'
  } else {
    options.private_chats = true
    options.private_groups = true
    options.private_channels = true
    enableSpecificChats.value = false
    enableMessageFilter.value = true
    enableMessageRange.value = false
    if (taskName.value === '快速导出任务') taskName.value = ''
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

function showInlineError(msg) {
  error.value = msg
  setTimeout(() => {
    if (error.value === msg) error.value = ''
  }, 4000)
}

function applyExactMessageLink() {
  const text = exactMessageLinkInput.value.trim()
  if (!text) return showInlineError('请先粘贴 Telegram 消息链接')

  const m = text.match(/https?:\/\/t\.me\/c\/(\d+)\/(\d+)/)
  if (!m) return showInlineError('目前只支持 https://t.me/c/<群组ID>/<消息ID> 这种链接')

  const rawChatId = parseInt(m[1], 10)
  const messageId = parseInt(m[2], 10)
  if (isNaN(rawChatId) || isNaN(messageId) || messageId <= 0) {
    return showInlineError('链接解析失败，请检查后重试')
  }

  const chatId = parseInt(`-100${rawChatId}`, 10)
  exactChatId.value = chatId
  exactMessageId.value = messageId
  exactChatTitle.value = ''
  exactMessagePreview.value = null
  applyQuickDefaults(chatId, messageId)
  taskName.value = `tg-${rawChatId}-${messageId}`
  error.value = ''
  resolveExactChatTitle(chatId)
  resolveExactMessagePreview(chatId, messageId)
}

function applyBatchPreset(mode) {
  if (!exactChatId.value || !exactMessageId.value) return showInlineError('请先粘贴并应用消息链接')

  enableSpecificChats.value = true
  enableMessageFilter.value = true
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

function setExportMode(mode) {
  exportMode.value = mode
  if (exactMessageId.value && mode === 'quick') {
    applyQuickDefaults(exactChatId.value, exactMessageId.value)
    return
  }
  applyModeDefaults(mode)
}

function resetToQuickMode() {
  step.value = 1
  exportMode.value = 'quick'
  error.value = ''
  taskName.value = ''
  specificChatsInput.value = ''
  filterMessagesInput.value = ''
  exactMessageLinkInput.value = ''
  exactMessageId.value = null
  exactChatId.value = null
  exactChatTitle.value = ''
  exactMessagePreview.value = null
  dateFrom.value = ''
  dateTo.value = ''
  enableSpecificChats.value = true
  enableMessageRange.value = false
  enableMessageFilter.value = false
  parsedChatIds.value = []
  parsedMessageIds.value = []

  Object.assign(options, defaultOptions())
  applyModeDefaults('quick')
}

function defaultOptions() {
  return {
    private_chats: true,
    bot_chats: false,
    private_groups: true,
    private_channels: true,
    public_groups: false,
    public_channels: false,
    only_my_messages: false,
    specific_chats: [],
    message_from: 1,
    message_to: 0,
    resume_download: true,
    skip_existing: true,
    photos: true,
    videos: true,
    voice_messages: true,
    video_messages: true,
    stickers: false,
    gifs: true,
    files: true,
    export_path: '/downloads',
    export_format: 'html',
    max_concurrent_downloads: 10,
    parallel_chunk_connections: 3,
    enable_parallel_chunk: false,
    download_speed_limit: 0,
    filter_mode: 'skip',
    filter_messages: [],
    proxy: ''
  }
}

const options = reactive(defaultOptions())

const formatText = {
  html: '人类可读的 HTML',
  json: '机器可读的 JSON',
  both: 'HTML + JSON'
}

function formatBytes(size) {
  if (!size || size <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let idx = 0
  let num = size
  while (num >= 1024 && idx < units.length - 1) {
    num /= 1024
    idx += 1
  }
  return `${num.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`
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
    return items.join('、') || '未选择'
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
    return items.join('、') || '未选择'
  }
  return ''
}

const summaryChatScope = computed(() => {
  if (enableSpecificChats.value && parsedChatIds.value.length > 0) {
    return `指定 ${parsedChatIds.value.length} 个聊天`
  }
  return getSummaryText('chats')
})

const summaryMessageRange = computed(() => {
  if (!enableMessageFilter.value || !enableMessageRange.value) return exportMode.value === 'quick' ? '未启用精确消息范围' : '全部历史'
  return options.message_to > 0 ? `${options.message_from} - ${options.message_to}` : `${options.message_from} - 最新`
})

const summaryMedia = computed(() => getSummaryText('media'))
const exportIntentLabel = computed(() => {
  if (exactMessageId.value && exactChatId.value) return '精确消息下载'
  if (enableSpecificChats.value && parsedChatIds.value.length > 0) return exportMode.value === 'quick' ? '快速定向导出' : '指定聊天导出'
  return exportMode.value === 'quick' ? '快速导出' : '高级归档导出'
})

const currentStepLabel = computed(() => steps.find(item => item.id === step.value)?.label || '范围')
const currentStepHint = computed(() => {
  if (step.value === 1) return exportMode.value === 'quick' ? '先锁定目标聊天或消息，再决定是否做精确消息过滤' : '决定聊天范围，并在消息过滤内设置历史范围与精细规则'
  if (step.value === 2) return '选择真正需要下载的媒体类型'
  if (step.value === 3) return '配置格式、下载策略与性能参数'
  return '确认摘要并创建导出任务'
})

async function quickStartFromLink() {
  if (!exactChatId.value || !exactMessageId.value) return showInlineError('请先粘贴并应用消息链接')
  if (!taskName.value) taskName.value = `tg-${String(exactChatId.value).replace('-100', '')}-${exactMessageId.value}`
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
    if (enableSpecificChats.value && parsedChatIds.value.length > 0) {
      options.specific_chats = parsedChatIds.value
    } else {
      options.specific_chats = []
    }

    if (!enableMessageRange.value) {
      options.message_from = 1
      options.message_to = 0
    } else {
      if (!options.message_from || options.message_from < 1) options.message_from = 1
      if (options.message_to == null || options.message_to < 0) options.message_to = 0
      if (options.message_to > 0 && options.message_to < options.message_from) {
        error.value = '消息范围无效：结束消息 ID 不能小于起始消息 ID'
        loading.value = false
        return
      }
    }

    if (dateFrom.value) options.date_from = new Date(dateFrom.value).toISOString()
    else delete options.date_from
    if (dateTo.value) options.date_to = new Date(dateTo.value).toISOString()
    else delete options.date_to

    if (enableMessageFilter.value && parsedMessageIds.value.length > 0) {
      options.filter_messages = parsedMessageIds.value
    } else {
      options.filter_mode = 'none'
      options.filter_messages = []
    }

    const headers = getAuthHeader()
    const createRes = await axios.post(
      `/api/export/create?name=${encodeURIComponent(taskName.value)}`,
      options,
      { headers }
    )

    await axios.post(`/api/export/${createRes.data.id}/start`, {}, { headers })
    router.push(`/tasks/${createRes.data.id}`)
  } catch (err) {
    error.value = err.response?.data?.detail || '创建任务失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.export-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.export-header {
  align-items: flex-start;
  gap: 16px;
}

.header-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.export-shell {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}

.summary-rail {
  position: sticky;
  top: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 18px;
}

.rail-header,
.summary-title-row,
.section-head,
.hero-top,
.toggle-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.eyebrow {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--primary-dark);
  font-weight: 700;
  margin-bottom: 6px;
}

.mode-badge,
.section-badge,
.summary-pill {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.mode-badge.quick,
.section-badge,
.summary-pill {
  background: rgba(24, 144, 255, 0.12);
  color: var(--primary-dark);
}

.mode-badge.advanced {
  background: rgba(250, 173, 20, 0.14);
  color: #9a6700;
}

.compact-card,
.soft-section {
  margin-bottom: 0;
}

.summary-list,
.stack-gap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.summary-item .label,
.field-label,
.preset-label,
.mini-muted {
  color: var(--text-secondary);
  font-size: 12px;
}

.summary-item .value,
.intent-highlight {
  color: var(--text);
  font-weight: 600;
}

.intent-highlight {
  line-height: 1.5;
}

.preview-bubble {
  margin-top: 12px;
  padding: 12px;
  background: #f7fafc;
  border: 1px solid #e8eef6;
  border-radius: 14px;
  color: var(--text-secondary);
  font-size: 13px;
}

.error-callout {
  padding: 12px 14px;
  background: #fff1f0;
  color: var(--danger);
  border: 1px solid #ffccc7;
  border-radius: 14px;
  font-weight: 600;
}

.export-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.stepper-desktop,
.stepper-mobile {
  padding: 14px;
}

.stepper-row,
.stepper-scroll {
  display: flex;
  gap: 10px;
}

.stepper-mobile {
  display: none;
}

.step-panel,
.step-chip {
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 16px;
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.step-panel {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
}

.step-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.step-panel.active,
.step-chip.active,
.step-panel.done,
.step-chip.done {
  border-color: rgba(24, 144, 255, 0.35);
  background: rgba(24, 144, 255, 0.08);
}

.step-panel .num,
.step-index {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #f0f2f5;
  font-weight: 700;
}

.step-layout,
.section-split {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-split {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.section-split.uneven {
  grid-template-columns: 1.1fr 0.9fr;
}

.hero-card,
.section-card {
  padding: 22px;
}

.helper-text,
.tile-desc,
.desc,
.summary-row .key {
  color: var(--text-secondary);
}

.helper-text.compact {
  font-size: 12px;
}

.mode-switch {
  display: inline-flex;
  gap: 8px;
  background: #f5f7fa;
  padding: 6px;
  border-radius: 14px;
}

.switch-btn,
.preset-chip {
  border: none;
  background: transparent;
  padding: 10px 14px;
  border-radius: 12px;
  cursor: pointer;
  font-weight: 600;
}

.switch-btn.active,
.preset-chip {
  background: #fff;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}

.hero-grid,
.selection-grid,
.radio-grid,
.preset-grid {
  display: grid;
  gap: 14px;
}

.hero-grid,
.preset-grid,
.radio-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.selection-grid {
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}

.hero-tile,
.selection-card,
.radio-card,
.soft-panel {
  border: 1px solid var(--border);
  border-radius: 18px;
  background: #fff;
}

.hero-tile,
.radio-card {
  padding: 16px;
}

.hero-tile {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.hero-tile.selected,
.selection-card.active,
.radio-card.active,
.radio-pill.active {
  border-color: rgba(24, 144, 255, 0.35);
  background: rgba(24, 144, 255, 0.06);
}

.tile-icon {
  font-size: 24px;
}

.tile-title,
.selection-card .title,
.radio-card strong {
  display: block;
  font-weight: 700;
  margin-bottom: 4px;
}

.selection-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px;
  cursor: pointer;
}

.selection-card input,
.radio-card input,
.inline-toggle input,
.radio-pill input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.inline-toggle {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  cursor: pointer;
}

.inline-toggle::before,
.radio-pill::before {
  content: '';
  width: 18px;
  height: 18px;
  border-radius: 999px;
  border: 2px solid #c8d2e1;
  background: #fff;
  flex-shrink: 0;
  margin-top: 2px;
}

.inline-toggle:has(input:checked)::before,
.radio-pill:has(input:checked)::before {
  border-color: var(--primary);
  background: var(--primary);
  box-shadow: inset 0 0 0 4px #fff;
}

.soft-panel {
  padding: 14px 16px;
}

.exact-link-form,
.cta-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.large-input {
  min-height: 48px;
}

.radio-group,
.tag-list {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.radio-pill {
  position: relative;
  display: inline-flex;
  gap: 10px;
  align-items: center;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  cursor: pointer;
  background: #fff;
}

.range-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.summary-table {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.summary-row {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f0f2f5;
}

.summary-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.action-footer {
  position: sticky;
  bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 16px 18px;
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(10px);
}

.footer-hint {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.footer-hint span {
  color: var(--text-secondary);
  font-size: 13px;
}

.footer-buttons {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.id-tag {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  background: var(--primary);
  color: white;
  border-radius: 999px;
  font-size: 12px;
  border: none;
  cursor: pointer;
}


.quick-mode-card {
  border: 1px solid rgba(24, 144, 255, 0.2);
  background: linear-gradient(180deg, rgba(24, 144, 255, 0.05), #fff 55%);
}

.quick-guide-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.quick-guide-tile {
  border: 1px solid #e8eef6;
  border-radius: 16px;
  padding: 14px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.quick-guide-tile strong {
  color: var(--text);
}

.quick-guide-tile span {
  color: var(--text-secondary);
  font-size: 13px;
}

.advanced-emphasis {
  border: 1px solid rgba(250, 173, 20, 0.22);
  background: linear-gradient(180deg, rgba(250, 173, 20, 0.05), #fff 55%);
}

@media (max-width: 1100px) {
  .export-shell {
    grid-template-columns: 1fr;
  }

  .summary-rail {
    position: static;
  }

  .stepper-mobile {
    display: block;
  }

  .stepper-desktop {
    display: none;
  }
}

@media (max-width: 768px) {
  .export-header,
  .hero-top,
  .section-head,
  .action-footer {
    flex-direction: column;
    align-items: stretch;
  }

  .section-split,
  .section-split.uneven,
  .hero-grid,
  .radio-grid,
  .range-grid,
  .preset-grid,
  .quick-guide-grid {
    grid-template-columns: 1fr;
  }

  .summary-row {
    grid-template-columns: 1fr;
    gap: 6px;
  }

  .summary-rail,
  .hero-card,
  .section-card,
  .card {
    padding: 16px;
  }

  .stepper-scroll {
    overflow-x: auto;
    padding-bottom: 2px;
  }
}
</style>
