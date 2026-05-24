-- 添加用户会话最后活动时间字段
-- 执行日期: 2026-05-23

-- 添加 last_activity_at 字段（非空，默认为当前时间）
ALTER TABLE user_sessions
ADD COLUMN last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW();

-- 添加 updated_at 字段
ALTER TABLE user_sessions
ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();

-- 更新现有记录的 last_activity_at（使用 login_at 作为默认值）
UPDATE user_sessions
SET last_activity_at = login_at
WHERE last_activity_at IS NULL OR last_activity_at = NOW();

-- 为 last_activity_at 创建索引
CREATE INDEX ix_user_sessions_last_activity_at ON user_sessions (last_activity_at);

-- 说明
-- last_activity_at: 用户最后一次活动时间，用于判断会话是否过期
-- updated_at: 记录更新时间，用于追踪会话状态变更
