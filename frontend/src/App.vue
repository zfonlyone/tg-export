<template>
  <div v-if="isLoggedIn" class="app-container">
    <!-- 侧边栏 / 顶部导航 -->
    <aside ref="sidebarEl" class="sidebar" :class="{ 'collapsed': isCollapsed }">
      <div class="sidebar-logo">
        <div class="brand-wrap">
          <h1 v-if="!isDesktopCollapsed || isMobile">📥 TG Export</h1>
          <h1 v-else>📥</h1>
          <!-- 移动端：显示当前页面标题（收纳态也保留），避免迷路 -->
          <div v-if="isMobile" class="nav-title" :title="navTitle">
            {{ navTitle }}
          </div>
        </div>
        <button @click="toggleSidebar" class="sidebar-toggle-btn" :title="toggleTitle">
          {{ toggleIcon }}
        </button>
      </div>
      <ul class="sidebar-nav">
        <li>
          <router-link to="/dashboard" active-class="active">
            <span class="icon">🏠</span>
            <span v-if="!isCollapsed">首页</span>
          </router-link>
        </li>
        <li>
          <router-link to="/export" active-class="active">
            <span class="icon">📥</span>
            <span v-if="!isCollapsed">导出数据</span>
          </router-link>
        </li>
        <li>
          <router-link to="/tasks" active-class="active">
            <span class="icon">📋</span>
            <span v-if="!isCollapsed">任务管理</span>
          </router-link>
        </li>
        <li>
          <router-link to="/settings" active-class="active">
            <span class="icon">⚙️</span>
            <span v-if="!isCollapsed">设置</span>
          </router-link>
        </li>
      </ul>
      <div class="sidebar-footer">
        <button @click="logout" class="btn btn-outline" style="width: 100%; color: rgba(255,255,255,0.8); border-color: rgba(255,255,255,0.3); padding: 8px 5px;">
          <span class="icon">🚪</span>
          <span v-if="!isCollapsed">退出登录</span>
        </button>
      </div>
    </aside>

    <!-- 主内容 -->
    <main class="main-content" :class="{ 'expanded': isDesktopCollapsed }">
      <div class="main-inner">
        <!-- 顶部导航栏（页面返回） -->
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
import { ref, onMounted, computed, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()

// 使用 ref 确保响应性
const isLoggedIn = ref(false)

// 断点：移动端顶部导航 / 桌面侧边栏
const isMobile = ref(false)
let mq = null

// 分离：桌面侧边栏折叠 vs 移动端顶部导航收纳（避免切换设备/缩放导致错位）
const isDesktopCollapsed = ref(localStorage.getItem('sidebarCollapsedDesktop') === 'true')
const isTopNavCollapsed = ref(localStorage.getItem('topNavCollapsed') === 'true')

const isCollapsed = computed(() => (isMobile.value ? isTopNavCollapsed.value : isDesktopCollapsed.value))

// 当前页标题（移动端顶部显示）
const navTitle = computed(() => {
  const p = route.path
  if (p.startsWith('/tasks/')) return '任务详情'
  if (p === '/tasks') return '任务管理'
  if (p === '/export') return '导出数据'
  if (p === '/settings') return '设置'
  if (p === '/dashboard' || p === '/') return '仪表盘'
  if (p === '/login') return '登录'
  return 'TG Export'
})

// DOM 引用：用于动态测量顶部条高度，防止缩放/字体变化导致错位
const sidebarEl = ref(null)

function updateMobileFlag() {
  isMobile.value = !!(mq && mq.matches)
}

function updateTopbarHeightVar() {
  // 只在移动端设置变量；桌面不需要
  if (!isMobile.value || !sidebarEl.value) {
    document.documentElement.style.removeProperty('--topbar-h')
    return
  }
  requestAnimationFrame(() => {
    if (!sidebarEl.value) return
    const h = sidebarEl.value.getBoundingClientRect().height
    document.documentElement.style.setProperty('--topbar-h', `${Math.ceil(h)}px`)
  })
}

const toggleIcon = computed(() => {
  if (isMobile.value) return isTopNavCollapsed.value ? '▼' : '▲'
  return isDesktopCollapsed.value ? '▶' : '◀'
})

const toggleTitle = computed(() => {
  if (isMobile.value) return isTopNavCollapsed.value ? '展开导航' : '收起导航'
  return isDesktopCollapsed.value ? '展开侧边栏' : '收起侧边栏'
})

function toggleSidebar() {
  if (isMobile.value) {
    isTopNavCollapsed.value = !isTopNavCollapsed.value
    localStorage.setItem('topNavCollapsed', isTopNavCollapsed.value)
  } else {
    isDesktopCollapsed.value = !isDesktopCollapsed.value
    localStorage.setItem('sidebarCollapsedDesktop', isDesktopCollapsed.value)
  }
  nextTick(() => updateTopbarHeightVar())
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
  nextTick(() => updateTopbarHeightVar())
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
  isLoggedIn.value = false // 立即更新状态
  router.push('/login')
}

// 任何会改变顶部条高度的状态变化，都触发重算
watch([isMobile, isTopNavCollapsed], () => nextTick(() => updateTopbarHeightVar()))

onMounted(() => {
  checkLoginStatus()
  showBackButton.value = route.path !== '/dashboard' && route.path !== '/'

  mq = window.matchMedia('(max-width: 768px)')
  updateMobileFlag()
  if (mq.addEventListener) mq.addEventListener('change', updateMobileFlag)
  else mq.addListener(updateMobileFlag)

  window.addEventListener('resize', updateTopbarHeightVar, { passive: true })
  updateTopbarHeightVar()
})

onBeforeUnmount(() => {
  if (mq) {
    if (mq.removeEventListener) mq.removeEventListener('change', updateMobileFlag)
    else mq.removeListener(updateMobileFlag)
  }
  window.removeEventListener('resize', updateTopbarHeightVar)
  document.documentElement.style.removeProperty('--topbar-h')
})
</script>

<style scoped>
.brand-wrap {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.nav-title {
  color: rgba(255, 255, 255, 0.78);
  font-weight: 600;
  font-size: 12px;
  letter-spacing: 0.2px;
  max-width: 40vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-footer .btn:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.5);
  color: #fff;
}
</style>
