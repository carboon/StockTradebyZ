/**
 * 前端测试全局设置文件
 * 提供 mock 和全局测试工具
 */

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {}

  return {
    getItem: (key: string): string | null => store[key] || null,
    setItem: (key: string, value: string): void => {
      store[key] = value.toString()
    },
    removeItem: (key: string): void => {
      delete store[key]
    },
    clear: (): void => {
      store = {}
    },
    get length(): number {
      return Object.keys(store).length
    },
    key: (index: number): string | null => {
      return Object.keys(store)[index] || null
    }
  }
})()

Object.defineProperty(global, 'localStorage', {
  value: localStorageMock,
  writable: true
})

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => {}
  })
})

// Mock IntersectionObserver
class IntersectionObserverMock {
  observe = () => {}
  disconnect = () => {}
  unobserve = () => {}
}

Object.defineProperty(global, 'IntersectionObserver', {
  writable: true,
  configurable: true,
  value: IntersectionObserverMock
})

// Mock ResizeObserver
class ResizeObserverMock {
  observe = () => {}
  disconnect = () => {}
  unobserve = () => {}
}

Object.defineProperty(global, 'ResizeObserver', {
  writable: true,
  configurable: true,
  value: ResizeObserverMock
})

// 全局测试工具
export const testUtils = {
  /**
   * 等待下一个 tick
   */
  async tick(): Promise<void> {
    await new Promise(resolve => setTimeout(resolve, 0))
  },

  /**
   * 等待指定时间
   */
  async wait(ms: number): Promise<void> {
    await new Promise(resolve => setTimeout(resolve, ms))
  },

  /**
   * 清除所有 mocks
   */
  clearMocks(): void {
    vi.clearAllMocks()
  },

  /**
   * 重置 localStorage
   */
  clearLocalStorage(): void {
    localStorage.clear()
  }
}
