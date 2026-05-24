-- 添加用户登录追踪功能
-- 执行日期: 2026-05-23

-- 添加用户登录追踪字段到 users 表
ALTER TABLE users
ADD COLUMN last_login_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE users
ADD COLUMN is_online BOOLEAN DEFAULT FALSE;

-- 创建用户登录会话表
CREATE TABLE user_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    login_at TIMESTAMP WITH TIME ZONE NOT NULL,
    logout_at TIMESTAMP WITH TIME ZONE,
    ip_address VARCHAR(50),
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 创建索引
CREATE INDEX ix_user_sessions_user_id_login_at ON user_sessions (user_id, login_at);
CREATE INDEX ix_user_sessions_login_at ON user_sessions (login_at);

-- 说明
-- last_login_at: 用户最后一次登录时间
-- is_online: 用户在线状态标识
-- user_sessions: 记录用户登录会话历史，包含登录时间、登出时间、IP地址和User Agent
