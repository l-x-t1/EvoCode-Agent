"""配置模块测试：加载、默认值、敏感字段遮蔽（额外检查 #7）。"""

from __future__ import annotations

from app.core.config import SensitiveStr, Settings


def test_settings_defaults():
    s = Settings()
    assert s.APP_NAME == "EvoCode Agent API"
    assert s.API_V1_PREFIX == "/api/v1"
    assert s.ENV in ("dev", "prod")


def test_allowed_origins_parsing():
    s = Settings(ALLOWED_ORIGINS="http://localhost:5173, http://localhost:3000")
    assert s.allowed_origins == ["http://localhost:5173", "http://localhost:3000"]


def test_sensitive_repr_masked():
    s = Settings(GLM_API_KEY=SensitiveStr("sk-real-secret-value"))
    r = repr(s)
    assert "sk-real-secret-value" not in r, "敏感值不得出现在 repr 中"
    assert s.GLM_API_KEY == "sk-real-secret-value", "实际取值不受遮蔽影响"


def test_sensitive_str_direct():
    v = SensitiveStr("abc")
    assert repr(v) == "'***'"
    assert str(v) == "abc"
