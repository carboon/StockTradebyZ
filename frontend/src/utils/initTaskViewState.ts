export type InitTaskViewTab = 'tasks' | 'logs' | 'status'

export interface InitTaskViewState {
  activeTab?: InitTaskViewTab
  selectedTaskId?: number | null
  bootstrapTaskId?: number | null
}

const INIT_TASK_VIEW_STATE_KEY = 'stocktrade:init-task-view'

function hasStorage(type: 'localStorage' | 'sessionStorage') {
  return typeof window !== 'undefined' && typeof window[type] !== 'undefined'
}

function readStorage(type: 'localStorage' | 'sessionStorage') {
  if (!hasStorage(type)) return null
  return window[type].getItem(INIT_TASK_VIEW_STATE_KEY)
}

export function loadInitTaskViewState(): InitTaskViewState {
  const raw = readStorage('localStorage') || readStorage('sessionStorage')
  if (!raw) return {}

  try {
    const parsed = JSON.parse(raw) as InitTaskViewState
    if (hasStorage('localStorage')) {
      window.localStorage.setItem(INIT_TASK_VIEW_STATE_KEY, JSON.stringify(parsed))
    }
    if (hasStorage('sessionStorage')) {
      window.sessionStorage.removeItem(INIT_TASK_VIEW_STATE_KEY)
    }
    return parsed
  } catch {
    if (hasStorage('localStorage')) {
      window.localStorage.removeItem(INIT_TASK_VIEW_STATE_KEY)
    }
    if (hasStorage('sessionStorage')) {
      window.sessionStorage.removeItem(INIT_TASK_VIEW_STATE_KEY)
    }
    return {}
  }
}

export function saveInitTaskViewState(patch: InitTaskViewState) {
  if (!hasStorage('localStorage')) return

  const current = loadInitTaskViewState()
  window.localStorage.setItem(
    INIT_TASK_VIEW_STATE_KEY,
    JSON.stringify({
      ...current,
      ...patch,
    })
  )
}

export function clearInitTaskViewState() {
  if (hasStorage('localStorage')) {
    window.localStorage.removeItem(INIT_TASK_VIEW_STATE_KEY)
  }
  if (hasStorage('sessionStorage')) {
    window.sessionStorage.removeItem(INIT_TASK_VIEW_STATE_KEY)
  }
}
