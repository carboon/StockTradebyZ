"""
Config API Tests
~~~~~~~~~~~~~~~~
配置管理API测试用例

测试配置管理相关的所有API端点，包括：
- 获取配置
- 更新配置
- 验证Tushare Token
- 保存环境变量
- 重新加载配置
- 获取Tushare状态

注意：
- 使用 test_client fixture 用于不需要直接访问数据库的测试
- 使用 test_client_with_db fixture 用于需要同时访问客户端和数据库的测试
"""
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.models import Config


@pytest.mark.api
def test_get_all_configs_empty(test_client: TestClient) -> None:
    """
    测试获取配置 - 空数据库

    验证在数据库为空时，API能正确返回从环境变量读取的配置。
    环境变量会被模拟为空值。
    """
    # 清除可能存在的环境变量
    env_keys = [
        "TUSHARE_TOKEN",
        "ZHIPUAI_API_KEY",
        "DASHSCOPE_API_KEY",
        "GEMINI_API_KEY",
        "DEFAULT_REVIEWER",
        "MIN_SCORE_THRESHOLD",
    ]
    original_values = {}
    for key in env_keys:
        original_values[key] = os.environ.get(key)
        if key in os.environ:
            del os.environ[key]

    try:
        response = test_client.get("/api/v1/config/")

        assert response.status_code == 200
        data = response.json()

        assert "configs" in data
        assert isinstance(data["configs"], list)

        # 验证返回了预期的配置项（即使值为空）
        config_keys = {c["key"] for c in data["configs"]}
        expected_keys = {
            "tushare_token",
            "zhipuai_api_key",
            "dashscope_api_key",
            "gemini_api_key",
            "default_reviewer",
            "min_score_threshold",
        }
        assert config_keys == expected_keys

        # 验证所有配置项都有必要的字段
        for config in data["configs"]:
            assert "key" in config
            assert "value" in config
            assert "description" in config

    finally:
        # 恢复原始环境变量
        for key, value in original_values.items():
            if value is not None:
                os.environ[key] = value


@pytest.mark.api
def test_get_all_configs(test_client_with_db: Any) -> None:
    """
    测试获取所有配置

    验证API能正确合并数据库配置和环境变量配置，并返回完整的配置列表。
    """
    # 添加数据库配置
    db_configs = [
        Config(key="custom_config_1", value="value1", description="自定义配置1"),
        Config(key="custom_config_2", value="value2", description="自定义配置2"),
    ]
    for config in db_configs:
        test_client_with_db.db.add(config)
    test_client_with_db.db.commit()

    # 设置一些环境变量
    os.environ["TUSHARE_TOKEN"] = "test_token_12345"

    try:
        response = test_client_with_db.get("/api/v1/config/")

        assert response.status_code == 200
        data = response.json()

        assert "configs" in data
        assert isinstance(data["configs"], list)

        # 验证返回的配置包含数据库中的配置
        config_dict = {c["key"]: c["value"] for c in data["configs"]}

        assert "custom_config_1" in config_dict
        assert config_dict["custom_config_1"] == "value1"
        assert "custom_config_2" in config_dict
        assert config_dict["custom_config_2"] == "value2"
        assert "tushare_token" in config_dict
        assert config_dict["tushare_token"] == "test_token_12345"

    finally:
        if "TUSHARE_TOKEN" in os.environ:
            del os.environ["TUSHARE_TOKEN"]


@pytest.mark.api
def test_update_config_single(test_client_with_db: Any) -> None:
    """
    测试更新单个配置项

    验证能够正确更新数据库中已存在的配置项。
    """
    # 先创建一个配置
    existing_config = Config(key="test_key", value="old_value", description="测试配置")
    test_client_with_db.db.add(existing_config)
    test_client_with_db.db.commit()

    # 更新配置
    response = test_client_with_db.put(
        "/api/v1/config/",
        json={"key": "test_key", "value": "new_value"},
    )

    assert response.status_code == 200
    data = response.json()

    assert data["key"] == "test_key"
    assert data["value"] == "new_value"

    # 验证数据库中的值确实被更新了
    test_client_with_db.db.rollback()  # 确保会话是最新的
    updated_config = test_client_with_db.db.query(Config).filter(Config.key == "test_key").first()
    assert updated_config is not None
    assert updated_config.value == "new_value"


@pytest.mark.api
def test_update_config_multiple(test_client_with_db: Any) -> None:
    """
    测试批量更新配置

    验证能够创建新的配置项并正确更新已存在的配置项。
    """
    # 先创建一个配置
    existing_config = Config(key="existing_key", value="old_value", description="已存在配置")
    test_client_with_db.db.add(existing_config)
    test_client_with_db.db.commit()

    # 更新已存在的配置
    response1 = test_client_with_db.put(
        "/api/v1/config/",
        json={"key": "existing_key", "value": "updated_value"},
    )
    assert response1.status_code == 200
    assert response1.json()["value"] == "updated_value"

    # 创建新配置
    response2 = test_client_with_db.put(
        "/api/v1/config/",
        json={"key": "new_key", "value": "new_value"},
    )
    assert response2.status_code == 200
    assert response2.json()["key"] == "new_key"
    assert response2.json()["value"] == "new_value"

    # 验证数据库中的状态
    test_client_with_db.db.rollback()
    configs = test_client_with_db.db.query(Config).all()
    assert len(configs) == 2

    config_dict = {c.key: c.value for c in configs}
    assert config_dict["existing_key"] == "updated_value"
    assert config_dict["new_key"] == "new_value"


@pytest.mark.api
def test_verify_tushare_success(test_client: TestClient) -> None:
    """
    测试验证Tushare Token - 成功场景

    Mock Tushare API返回有效数据，验证Token验证成功。
    """
    with patch("app.api.config.TushareService") as mock_service_class:
        mock_service = MagicMock()
        mock_service.verify_token.return_value = (True, "Token 验证成功")
        mock_service_class.return_value = mock_service

        response = test_client.post(
            "/api/v1/config/verify-tushare",
            json={"token": "valid_token_12345"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["valid"] is True
        assert data["message"] == "Token 验证成功"

        # 验证服务被正确调用
        mock_service_class.assert_called_once_with(token="valid_token_12345")
        mock_service.verify_token.assert_called_once()


@pytest.mark.api
def test_verify_tushare_failure(test_client: TestClient) -> None:
    """
    测试验证Tushare Token - 失败场景

    Mock Tushare API返回无效结果，验证Token验证失败时的错误处理。
    """
    with patch("app.api.config.TushareService") as mock_service_class:
        mock_service = MagicMock()
        mock_service.verify_token.return_value = (False, "Token 无效")
        mock_service_class.return_value = mock_service

        response = test_client.post(
            "/api/v1/config/verify-tushare",
            json={"token": "invalid_token"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["valid"] is False
        assert data["message"] == "Token 无效"


@pytest.mark.api
def test_verify_tushare_exception(test_client: TestClient) -> None:
    """
    测试验证Tushare Token - 异常场景

    验证当服务抛出异常时，API能正确处理并返回错误信息。
    """
    with patch("app.services.tushare_service.TushareService") as mock_service_class:
        mock_service_class.side_effect = Exception("网络连接失败")

        response = test_client.post(
            "/api/v1/config/verify-tushare",
            json={"token": "test_token"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["valid"] is False
        assert "验证失败" in data["message"]


@pytest.mark.api
def test_save_env(test_client: TestClient) -> None:
    """
    测试保存环境变量

    Mock文件写入操作，验证环境变量能正确保存到.env文件。
    """
    mock_env_content = "# Existing config\nEXISTING_KEY=existing_value\n"

    with patch("builtins.open", MagicMock()) as mock_open:
        mock_file = MagicMock()
        mock_file.readlines.return_value = mock_env_content.splitlines(keepends=True)
        mock_open.return_value.__enter__.return_value = mock_file

        response = test_client.post(
            "/api/v1/config/save-env",
            json={
                "tushare_token": "new_token",
                "zhipuai_api_key": "new_api_key",
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "ok"
        assert data["message"] == "环境变量已保存"

        assert mock_open.called


@pytest.mark.api
def test_save_env_update_existing(test_client: TestClient) -> None:
    """
    测试保存环境变量 - 更新已存在的配置

    验证当.env文件中已存在某个配置时，能够正确更新而不是重复添加。
    """
    existing_content = "TUSHARE_TOKEN=old_token\nZHIPUAI_API_KEY=old_key\n"

    with patch("builtins.open", MagicMock()) as mock_open:
        mock_file = MagicMock()
        mock_file.readlines.return_value = existing_content.splitlines(keepends=True)
        mock_open.return_value.__enter__.return_value = mock_file

        response = test_client.post(
            "/api/v1/config/save-env",
            json={"tushare_token": "updated_token"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "ok"
        assert "message" in data


@pytest.mark.api
def test_reload_config(test_client: TestClient) -> None:
    """
    测试重新加载配置

    验证配置缓存清除功能，确保配置能够被重新加载。
    """
    with patch("app.api.config.get_settings") as mock_get_settings:
        mock_settings = MagicMock()
        mock_settings.cache_clear = MagicMock()
        mock_get_settings.cache_clear = MagicMock()

        response = test_client.get("/api/v1/config/reload")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "ok"
        assert data["message"] == "配置已重新加载"


@pytest.mark.api
def test_get_tushare_status_configured(test_client: TestClient) -> None:
    """
    测试获取Tushare状态 - 已配置Token

    验证当已配置Tushare Token时，API返回正确的状态信息。
    """
    test_token = "12345678abcdef1234567890"
    os.environ["TUSHARE_TOKEN"] = test_token

    mock_data_status = {
        "raw_data": {"exists": True, "count": 10, "latest_date": "2024-01-15"},
        "candidates": {"exists": True, "count": 5, "latest_date": "2024-01-15"},
        "analysis": {"exists": False, "count": 0, "latest_date": None},
        "kline": {"exists": True, "count": 20, "latest_date": None},
    }

    try:
        with patch("app.services.tushare_service.TushareService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.check_data_status.return_value = mock_data_status
            mock_service_class.return_value = mock_service

            response = test_client.get("/api/v1/config/tushare-status")

            assert response.status_code == 200
            data = response.json()

            assert data["configured"] is True
            assert "token_prefix" in data
            assert data["token_prefix"] == "12345678..."
            assert "data_status" in data
            assert data["data_status"] == mock_data_status

    finally:
        if "TUSHARE_TOKEN" in os.environ:
            del os.environ["TUSHARE_TOKEN"]


@pytest.mark.api
def test_get_tushare_status_not_configured(test_client: TestClient) -> None:
    """
    测试获取Tushare状态 - 未配置Token

    验证当未配置Tushare Token时，API返回未配置状态。
    """
    if "TUSHARE_TOKEN" in os.environ:
        del os.environ["TUSHARE_TOKEN"]

    response = test_client.get("/api/v1/config/tushare-status")

    assert response.status_code == 200
    data = response.json()

    assert data["configured"] is False
    assert "token_prefix" not in data
    assert "data_status" not in data


@pytest.mark.api
def test_get_tushare_status_with_error(test_client: TestClient) -> None:
    """
    测试获取Tushare状态 - 服务异常

    验证当Tushare服务抛出异常时，API能正确处理错误。
    """
    test_token = "test_token_with_error"
    os.environ["TUSHARE_TOKEN"] = test_token

    try:
        with patch("app.services.tushare_service.TushareService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.check_data_status.side_effect = Exception("服务不可用")
            mock_service_class.return_value = mock_service

            response = test_client.get("/api/v1/config/tushare-status")

            assert response.status_code == 200
            data = response.json()

            assert data["configured"] is True
            assert "error" in data
            assert "服务不可用" in data["error"]

    finally:
        if "TUSHARE_TOKEN" in os.environ:
            del os.environ["TUSHARE_TOKEN"]


@pytest.mark.api
def test_update_config_description_preserved(test_client_with_db: Any) -> None:
    """
    测试更新配置时保留描述信息

    验证更新配置值时，原有的description字段会被保留。
    """
    # 创建带描述的配置
    config = Config(
        key="test_key",
        value="old_value",
        description="这是一个测试配置"
    )
    test_client_with_db.db.add(config)
    test_client_with_db.db.commit()

    # 更新配置值
    response = test_client_with_db.put(
        "/api/v1/config/",
        json={"key": "test_key", "value": "new_value"},
    )

    assert response.status_code == 200
    data = response.json()

    assert data["key"] == "test_key"
    assert data["value"] == "new_value"
    assert data["description"] == "这是一个测试配置"


@pytest.mark.api
def test_get_tushare_status_short_token(test_client: TestClient) -> None:
    """
    测试获取Tushare状态 - 短Token

    验证当Token长度小于等于8时，token_prefix的格式正确。
    """
    short_token = "abc123"
    os.environ["TUSHARE_TOKEN"] = short_token

    try:
        with patch("app.services.tushare_service.TushareService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.check_data_status.return_value = {
                "raw_data": {"exists": False, "count": 0, "latest_date": None},
                "candidates": {"exists": False, "count": 0, "latest_date": None},
                "analysis": {"exists": False, "count": 0, "latest_date": None},
                "kline": {"exists": False, "count": 0, "latest_date": None},
            }
            mock_service_class.return_value = mock_service

            response = test_client.get("/api/v1/config/tushare-status")

            assert response.status_code == 200
            data = response.json()

            assert data["configured"] is True
            assert data["token_prefix"] == "***"

    finally:
        if "TUSHARE_TOKEN" in os.environ:
            del os.environ["TUSHARE_TOKEN"]


@pytest.mark.api
def test_get_all_configs_with_empty_env(test_client_with_db: Any) -> None:
    """
    测试获取配置 - 空环境变量但有数据库配置

    验证当环境变量为空时，数据库配置仍然能正常返回。
    """
    # 清除环境变量
    env_keys = ["TUSHARE_TOKEN", "DEFAULT_REVIEWER"]
    original_values = {}
    for key in env_keys:
        original_values[key] = os.environ.get(key)
        if key in os.environ:
            del os.environ[key]

    # 添加数据库配置
    db_config = Config(key="db_only_config", value="db_value", description="仅数据库配置")
    test_client_with_db.db.add(db_config)
    test_client_with_db.db.commit()

    try:
        response = test_client_with_db.get("/api/v1/config/")

        assert response.status_code == 200
        data = response.json()

        config_dict = {c["key"]: c["value"] for c in data["configs"]}
        assert "db_only_config" in config_dict
        assert config_dict["db_only_config"] == "db_value"

    finally:
        for key, value in original_values.items():
            if value is not None:
                os.environ[key] = value
