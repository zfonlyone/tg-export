<template>
  <div v-if="isLoggedIn" class="app-container">
    <!-- 侧边栏 -->
    <aside class="sidebar" :class="{ 'collapsed': isSidebarCollapsed }">
      <div class="sidebar-logo">
        <h1 v-if="!isSidebarCollapsed || isMobile">📥 TG Export</h1>
        <h1 v-else>📥</h1>
        <button @click="toggleSidebar" class="sidebar-toggle-btn" :title="toggleTitle">
          {{ toggleIcon }}
        </button>
      </div>
      <ul class="sidebar-nav">
        <li>
          <router-link to="/dashboard" active-class="active">
            <span class="icon">🏠</span>
            <span v-if="!isSidebarCollapsed">首页</span>
          </router-link>
        </li>
        <li>
          <router-link to="/export" active-class="active">
            <span class="icon">📥</span>
            <span v-if="!isSidebarCollapsed">导出数据</span>
          </router-link>
        </li>
        <li>
          <router-link to="/tasks" active-class="active">
            <span class="icon">📋</span>
            <span v-if="!isSidebarCollapsed">任务管理</span>
          </router-link>
        </li>
        <li>
          <router-link to="/settings" active-class="active">
            <span class="icon">⚙️</span>
            <span v-if="!isSidebarCollapsed">设置</span>
          </router-link>
        </li>
      </ul>
      <div class="sidebar-footer">
        <button @click="logout" class="btn btn-outline" style="width: 100%; color: rgba(255,255,255,0.8); border-color: rgba(255,255,255,0.3); padding: 8px 5px;">
          <span class="icon">🚪</span>
          <span v-if="!isSidebarCollapsed">退出登录</span>
        </button>
      </div>
    </aside>

    <!-- 主内容 -->
    <main class="main-content" :class="{ 'expanded': isSidebarCollapsed }">
      <div class="main-inner">
        <!-- 顶部导航栏 -->
        <div class="top-bar" v-if="showBackButton">
          <button @click="goBack" class="btn btn-outline btn-sm">
            ← 返回
          </button>
          <router-link to="/dashboard" class="btn btn-outline btn-sm" style="margin-left: 10px;">
            🏠 首页
          </router-link>
        </div>
        <router-view />
      </div>
    </main>
  </div>

  <!-- 未登录时直接显示路由 -->
  <router-view v-else />
</template>

<script setup>
import { ref, onMounted, computed, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()

// 使用 ref 确保响应性
const isLoggedIn = ref(false)
const isSidebarCollapsed = ref(localStorage.getItem('sidebarCollapsed') === 'true')

// 移动端识别：用于顶部模式下的“上下收纳”按钮
const isMobile = ref(false)
let mq = null

function updateMobileFlag() {
  isMobile.value = !!(mq && mq.matches)
}

const toggleIcon = computed(() => {
  if (isMobile.value) return isSidebarCollapsed.value ? '▼' : '▲'
  return isSidebarCollapsed.value ? '▶' : '◀'
})

const toggleTitle = computed(() => {
  if (isMobile.value) return isSidebarCollapsed.value ? '展开' : '收起'
  return isSidebarCollapsed.value ? '展开' : '收起'
})

function toggleSidebar() {
  isSidebarCollapsed.value = !isSidebarCollapsed.value
  localStorage.setItem('sidebarCollapsed', isSidebarCollapsed.value)
}

// 检查登录状态
function checkLoginStatus() {
  isLoggedIn.value = !!localStorage.getItem('token')
}

// 在非首页显示返回按钮
const showBackButton = ref(false)

// 监听路由变化
router.afterEach((to) => {
  showBackButton.value = to.path !== '/dashboard' && to.path !== '/'
  checkLoginStatus()
})

function goBack() {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/dashboard')
  }
}

function logout() {
  localStorage.removeItem('token')
  isLoggedIn.value = false  // 立即更新状态
  router.push('/login')
}

onMounted(() => {
  checkLoginStatus()
  showBackButton.value = route.path !== '/dashboard' && route.path !== '/'

  mq = window.matchMedia('(max-width: 768px)')
  updateMobileFlag()
  // 兼容新旧浏览器
  if (mq.addEventListener) mq.addEventListener('change', updateMobileFlag)
  else mq.addListener(updateMobileFlag)
})

onBeforeUnmount(() => {
  if (!mq) return
  if (mq.removeEventListener) mq.removeEventListener('change', updateMobileFlag)
  else mq.removeListener(updateMobileFlag)
})
</script>

<style scoped>
.sidebar-footer .btn:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.5);
  color: #fff;
}
</style>
