const INITIALIZATION_HINTS = [
  '请先完成首次初始化',
  '首次初始化',
  '数据初始化',
  '全量初始化',
  '系统尚未完成初始化',
]

export function isInitializationPendingError(error: unknown): boolean {
  const message = String((error as Error | undefined)?.message || '')
  return INITIALIZATION_HINTS.some((hint) => message.includes(hint))
}

export function getUserSafeErrorMessage(error: unknown, fallback: string): string {
  if (isInitializationPendingError(error)) {
    return '系统尚未完成初始化'
  }
  return (error as Error | undefined)?.message || fallback
}
