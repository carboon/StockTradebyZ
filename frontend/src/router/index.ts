import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/tomorrow-star',
  },
  {
    path: '/config',
    name: 'Config',
    component: () => import('@/views/Config.vue'),
    meta: { title: '配置管理', icon: 'Setting' },
  },
  {
    path: '/update',
    name: 'Update',
    component: () => import('@/views/Update.vue'),
    meta: { title: '运维管理', icon: 'Refresh' },
  },
  {
    path: '/tomorrow-star',
    name: 'TomorrowStar',
    component: () => import('@/views/TomorrowStar.vue'),
    meta: { title: '明日之星', icon: 'Star', keepAlive: true },
  },
  {
    path: '/diagnosis',
    name: 'Diagnosis',
    component: () => import('@/views/Diagnosis.vue'),
    meta: { title: '单股诊断', icon: 'Search', keepAlive: true },
  },
  {
    path: '/watchlist',
    name: 'Watchlist',
    component: () => import('@/views/Watchlist.vue'),
    meta: { title: '重点观察', icon: 'View', keepAlive: true },
  },
  {
    path: '/system-info',
    name: 'SystemInfo',
    component: () => import('@/views/SystemInfo.vue'),
    meta: { title: '系统说明', icon: 'Document' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  document.title = `${to.meta.title || 'StockTrader'} - StockTrader 2.0`
  next()
})

export default router
