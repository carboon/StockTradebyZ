"""
Usage Tracking Middleware 测试
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
测试批量聚合写入策略的正确性
"""
import time
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI, Request
from starlette.responses import Response

from app.middleware.usage import UsageTrackingMiddleware, _usage_buffer, flush_usage_buffer


@pytest.fixture
def app():
    """创建测试应用。"""
    return FastAPI()


@pytest.fixture
def client(app):
    """创建测试客户端。"""
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_buffer():
    """每个测试前清空缓冲区。"""
    _usage_buffer._buffer.clear()
    _usage_buffer._last_flush = time.time()
    yield
    _usage_buffer._buffer.clear()


class TestUsageTrackingMiddleware:
    """UsageTrackingMiddleware 测试"""

    def test_skip_health_check(self, app):
        """测试跳过健康检查路径。"""
        app.add_middleware(UsageTrackingMiddleware)

        @app.get("/health")
        def health():
            return {"status": "ok"}

        from fastapi.testclient import TestClient
        client = TestClient(app)

        with patch.object(_usage_buffer, 'add') as mock_add:
            response = client.get("/health")
            assert response.status_code == 200
            mock_add.assert_not_called()

    def test_skip_docs(self, app):
        """测试跳过文档路径。"""
        app.add_middleware(UsageTrackingMiddleware)

        @app.get("/docs")
        def docs():
            return {"docs": "ok"}

        from fastapi.testclient import TestClient
        client = TestClient(app)

        with patch.object(_usage_buffer, 'add') as mock_add:
            response = client.get("/docs")
            assert response.status_code == 200
            mock_add.assert_not_called()

    def test_log_api_request(self, app):
        """测试记录API请求。"""
        app.add_middleware(UsageTrackingMiddleware)

        @app.get("/api/stocks")
        def stocks():
            return {"stocks": []}

        from fastapi.testclient import TestClient
        client = TestClient(app)

        with patch.object(_usage_buffer, 'add') as mock_add:
            response = client.get("/api/stocks")
            assert response.status_code == 200
            mock_add.assert_called_once()

            call_args = mock_add.call_args[0][0]
            assert call_args["endpoint"] == "/api/stocks"
            assert call_args["method"] == "GET"
            assert call_args["status_code"] == 200

    def test_buffer_aggregation(self):
        """测试缓冲区聚合功能。"""
        # 添加多条记录
        for i in range(10):
            _usage_buffer.add({
                "endpoint": f"/api/test/{i}",
                "method": "GET",
                "status_code": 200,
            })

        assert len(_usage_buffer._buffer) == 10

    def test_flush_threshold(self):
        """测试达到阈值时自动刷新。"""
        # 设置低阈值用于测试
        original_threshold = _usage_buffer._flush_threshold
        _usage_buffer._flush_threshold = 5

        try:
            with patch.object(_usage_buffer, '_flush_now') as mock_flush:
                # 添加达到阈值的记录
                for i in range(5):
                    _usage_buffer.add({
                        "endpoint": f"/api/test/{i}",
                        "method": "GET",
                        "status_code": 200,
                    })

                # 验证flush被调用
                mock_flush.assert_called_once()
        finally:
            _usage_buffer._flush_threshold = original_threshold

    def test_manual_flush(self):
        """测试手动刷新功能。"""
        # 添加记录
        _usage_buffer.add({
            "endpoint": "/api/test",
            "method": "GET",
            "status_code": 200,
        })

        assert len(_usage_buffer._buffer) > 0

        # 手动刷新
        flush_usage_buffer()

        # 缓冲区应该被清空（注意：实际数据库写入可能失败，但缓冲区会清空）
        assert len(_usage_buffer._buffer) == 0


class TestUsageBuffer:
    """UsageBuffer 独立测试"""

    def test_add_to_buffer(self):
        """测试添加到缓冲区。"""
        _usage_buffer.add({
            "user_id": 1,
            "endpoint": "/api/test",
            "method": "GET",
            "status_code": 200,
        })

        assert len(_usage_buffer._buffer) == 1
        assert _usage_buffer._buffer[0]["user_id"] == 1

    def test_concurrent_add(self):
        """测试并发添加。"""
        import threading

        def add_records(count):
            for i in range(count):
                _usage_buffer.add({
                    "endpoint": f"/api/test/{i}",
                    "method": "GET",
                    "status_code": 200,
                })

        threads = [
            threading.Thread(target=add_records, args=(10,))
            for _ in range(3)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 验证所有记录都被添加
        assert len(_usage_buffer._buffer) == 30


class TestApiKeyUpdateOptimization:
    """API Key更新优化测试"""

    def test_api_key_update_throttling(self, db):
        """测试API Key更新节流。"""
        from app.api.deps import _api_key_last_update_cache, _API_KEY_UPDATE_INTERVAL
        from app.models import ApiKey, User
        from app.time_utils import utc_now
        import time

        # 创建测试用户和API Key
        user = User(username="test_user", email="test@example.com", hashed_password="hash")
        db.add(user)
        db.commit()

        api_key = ApiKey(
            user_id=user.id,
            key_hash="test_hash",
            name="test_key",
        )
        db.add(api_key)
        db.commit()

        # 模拟第一次更新
        first_time = time.time()
        _api_key_last_update_cache[api_key.id] = first_time

        # 模拟立即第二次验证（不应更新）
        current_time = time.time()
        should_update = (current_time - _api_key_last_update_cache.get(api_key.id, 0)) >= _API_KEY_UPDATE_INTERVAL

        assert not should_update, "不应立即更新API Key"

        # 模拟超过时间窗口后的验证
        _api_key_last_update_cache[api_key.id] = first_time - _API_KEY_UPDATE_INTERVAL - 1
        should_update = (time.time() - _api_key_last_update_cache.get(api_key.id, 0)) >= _API_KEY_UPDATE_INTERVAL

        assert should_update, "超过时间窗口后应更新API Key"

        # 清理
        db.delete(api_key)
        db.delete(user)
        db.commit()
