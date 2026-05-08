class RetryableBackgroundUpdateError(RuntimeError):
    """可由 systemd 自动重试的后台更新异常。"""
