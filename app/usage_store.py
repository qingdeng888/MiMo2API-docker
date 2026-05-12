"""用量统计持久化存储（JSON 文件，按模型/API Key/账号分组 + 按日累计）"""

import json
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta

_USAGE_FILE = Path(__file__).parent.parent / "usage.json"
_LOCK = threading.Lock()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load() -> dict:
    if not _USAGE_FILE.exists():
        return _empty_state()
    try:
        with open(_USAGE_FILE, "r") as f:
            data = json.load(f)
        for key in ("models", "total", "daily"):
            if key not in data:
                data[key] = {} if key == "daily" else (_zero_count() if key == "total" else {})
        # 兼容旧版：确保新字段存在
        if "api_keys" not in data:
            data["api_keys"] = {}
        if "accounts" not in data:
            data["accounts"] = {}
        return data
    except Exception:
        return _empty_state()


def _save(data: dict):
    tmp = _USAGE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(_USAGE_FILE)


def _empty_state() -> dict:
    return {"models": {}, "total": _zero_count(), "daily": {}, "api_keys": {}, "accounts": {}}


def _zero_count() -> dict:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "requests": 0}


def add_usage(model: str, prompt_tokens: int, completion_tokens: int,
              api_key: str = None, account_id: str = None):
    """累加一次用量（线程安全）。

    Args:
        model: 模型名
        prompt_tokens: 输入 token 数
        completion_tokens: 输出 token 数
        api_key: 请求使用的 API Key（可选，用于按 Key 统计）
        account_id: 使用的 MiMo 账号 user_id（可选，用于按账号统计）
    """
    with _LOCK:
        data = _load()
        day = _today()

        # 按模型（累计）
        if model not in data["models"]:
            data["models"][model] = _zero_count()
        m = data["models"][model]
        m["prompt_tokens"] += prompt_tokens
        m["completion_tokens"] += completion_tokens
        m["total_tokens"] += prompt_tokens + completion_tokens
        m["requests"] += 1

        # 全部累计
        t = data["total"]
        t["prompt_tokens"] += prompt_tokens
        t["completion_tokens"] += completion_tokens
        t["total_tokens"] += prompt_tokens + completion_tokens
        t["requests"] += 1

        # 按日累计
        if day not in data["daily"]:
            data["daily"][day] = {}
        if model not in data["daily"][day]:
            data["daily"][day][model] = _zero_count()
        dm = data["daily"][day][model]
        dm["prompt_tokens"] += prompt_tokens
        dm["completion_tokens"] += completion_tokens
        dm["total_tokens"] += prompt_tokens + completion_tokens
        dm["requests"] += 1

        # 按 API Key 累计
        if api_key:
            # 提取实际 key（去掉 Bearer 前缀），截断显示
            key_raw = api_key.replace("Bearer ", "").strip()
            key_label = key_raw[:8] + "..." + key_raw[-4:] if len(key_raw) > 16 else key_raw
            if "api_keys" not in data:
                data["api_keys"] = {}
            if key_label not in data["api_keys"]:
                data["api_keys"][key_label] = _zero_count()
            ak = data["api_keys"][key_label]
            ak["prompt_tokens"] += prompt_tokens
            ak["completion_tokens"] += completion_tokens
            ak["total_tokens"] += prompt_tokens + completion_tokens
            ak["requests"] += 1

        # 按 MiMo 账号累计
        if account_id:
            if "accounts" not in data:
                data["accounts"] = {}
            if account_id not in data["accounts"]:
                data["accounts"][account_id] = _zero_count()
            ac = data["accounts"][account_id]
            ac["prompt_tokens"] += prompt_tokens
            ac["completion_tokens"] += completion_tokens
            ac["total_tokens"] += prompt_tokens + completion_tokens
            ac["requests"] += 1

        _save(data)


def _merge_days(days_data: dict) -> dict:
    """合并多天的模型用量为一个汇总。"""
    merged = {}
    for day, models in days_data.items():
        for model, counts in models.items():
            if model not in merged:
                merged[model] = _zero_count()
            for k in ("prompt_tokens", "completion_tokens", "total_tokens", "requests"):
                merged[model][k] += counts.get(k, 0)
    return merged


def get_usage() -> dict:
    """返回用量统计：今天 / 本周 / 全部，按模型分组 + 按 API Key + 按账号。"""
    data = _load()
    today = _today()
    week_start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    # 今天
    today_data = data.get("daily", {}).get(today, {})

    # 本周（最近 7 天）
    week_days = {d: v for d, v in data.get("daily", {}).items() if d >= week_start}

    return {
        "today": {
            "models": today_data,
            "total": _sum_models(today_data),
        },
        "week": {
            "models": _merge_days(week_days),
            "total": _sum_models(_merge_days(week_days)),
        },
        "total": {
            "models": data.get("models", {}),
            "total": data.get("total", _zero_count()),
        },
        "api_keys": data.get("api_keys", {}),
        "accounts": data.get("accounts", {}),
    }


def _sum_models(models: dict) -> dict:
    """合并所有模型的用量为一个 total。"""
    total = _zero_count()
    for counts in models.values():
        for k in ("prompt_tokens", "completion_tokens", "total_tokens", "requests"):
            total[k] += counts.get(k, 0)
    return total


def clear_usage():
    """清空全部用量统计数据。"""
    with _LOCK:
        _save(_empty_state())
