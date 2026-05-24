/**
 * usePollingManager - 统一轮询管理器
 *
 * 集中管理所有轮询任务，确保：
 * 1. 每个轮询有唯一的 key，不会重复注册
 * 2. 页面 deactivated 时自动停止对应轮询
 * 3. 只有活跃页面的轮询才会运行
 * 4. 组件卸载时自动清理所有定时器
 */

type PollingCallback = () => Promise<void> | void

interface PollingEntry {
  key: string
  callback: PollingCallback
  intervalMs: number
  timerId: ReturnType<typeof setInterval> | null
  active: boolean
  immediateFirstRun: boolean
}

/** 所有已注册的轮询条目 */
const registry = new Map<string, PollingEntry>()

/** 当前活跃的页面标识（同时只允许一个页面活跃轮询） */
let activePageId: string | null = null

/**
 * 注册一个轮询任务
 * @param key 唯一标识，如 'pageLayout:taskStatus'
 * @param callback 轮询回调
 * @param intervalMs 轮询间隔（毫秒）
 * @param options 可选配置
 */
export function registerPoll(
  key: string,
  callback: PollingCallback,
  intervalMs: number,
  options?: { immediateFirstRun?: boolean },
): void {
  // 如果已有同名轮询在运行，先停止旧的
  const existing = registry.get(key)
  if (existing?.timerId) {
    clearInterval(existing.timerId)
  }

  const entry: PollingEntry = {
    key,
    callback,
    intervalMs,
    timerId: null,
    active: false,
    immediateFirstRun: options?.immediateFirstRun ?? false,
  }

  registry.set(key, entry)
}

/**
 * 启动指定 key 的轮询（仅在页面活跃时调用）
 */
export function startPoll(key: string): void {
  const entry = registry.get(key)
  if (!entry) return

  // 先停止旧的定时器
  stopPoll(key)

  entry.active = true

  // 如果需要立即执行一次
  if (entry.immediateFirstRun) {
    void entry.callback()
  }

  entry.timerId = setInterval(() => {
    if (document.visibilityState === 'hidden') return
    void entry.callback()
  }, entry.intervalMs)
}

/**
 * 停止指定 key 的轮询
 */
export function stopPoll(key: string): void {
  const entry = registry.get(key)
  if (!entry) return

  if (entry.timerId) {
    clearInterval(entry.timerId)
    entry.timerId = null
  }
  entry.active = false
}

/**
 * 更新指定轮询的间隔，如果正在运行则重启
 */
export function updatePollInterval(key: string, newIntervalMs: number): void {
  const entry = registry.get(key)
  if (!entry) return

  entry.intervalMs = newIntervalMs

  // 如果正在运行，重启以应用新间隔
  if (entry.active) {
    startPoll(key)
  }
}

/**
 * 注销一个轮询任务并清理资源
 */
export function unregisterPoll(key: string): void {
  stopPoll(key)
  registry.delete(key)
}

/**
 * 设置当前活跃页面，自动停止非当前页面的专属轮询
 * 全局轮询（不以页面 ID 为前缀的）不受影响
 *
 * @param pageId 页面标识，如 'tomorrow-star', 'diagnosis', 'update'
 */
export function setActivePage(pageId: string): void {
  const previousPage = activePageId
  activePageId = pageId

  // 停止上一个活跃页面的专属轮询
  if (previousPage && previousPage !== pageId) {
    stopPagePolls(previousPage)
  }
}

/**
 * 停止属于指定页面的所有轮询
 * 约定：轮询 key 格式为 "pageId:xxx" 的属于该页面
 */
export function stopPagePolls(pageId: string): void {
  for (const key of registry.keys()) {
    if (key.startsWith(`${pageId}:`)) {
      stopPoll(key)
    }
  }
}

/**
 * 页面 activated 时激活其专属轮询
 * 约定：轮询 key 格式为 "pageId:xxx" 的属于该页面
 */
export function activatePagePolls(pageId: string): void {
  setActivePage(pageId)
  for (const [key, entry] of registry) {
    if (key.startsWith(`${pageId}:`) && !entry.active) {
      startPoll(key)
    }
  }
}

/**
 * 页面 deactivated 时停止其专属轮询
 */
export function deactivatePagePolls(pageId: string): void {
  stopPagePolls(pageId)
}

/**
 * 获取当前活跃页面 ID
 */
export function getActivePage(): string | null {
  return activePageId
}

/**
 * 清理所有轮询（应用卸载时调用）
 */
export function cleanupAllPolls(): void {
  for (const entry of registry.values()) {
    if (entry.timerId) {
      clearInterval(entry.timerId)
    }
  }
  registry.clear()
  activePageId = null
}

/**
 * 检查指定轮询是否正在运行
 */
export function isPollActive(key: string): boolean {
  return registry.get(key)?.active ?? false
}
