"""智能账号池调度器 — 防风控轮询

功能：
  1. 请求频率控制：每个账号有最小请求间隔
  2. 错误退避：账号出错后自动冷却，连续出错指数退避
  3. 权重调度：根据账号健康度动态调整选择概率
  4. 并发限制：每个账号同时最多 N 个并发请求
  5. 账号健康监控：记录成功/失败次数，自动标记不可用账号
"""

import time
import threading
import random
from dataclasses import dataclass, field
from typing import Optional, List
from .config import MimoAccount


# ─── 配置常量 ─────────────────────────────────────────────────

# 每个账号的最小请求间隔（秒）
MIN_REQUEST_INTERVAL = 3.0

# 每个账号最大并发请求数
MAX_CONCURRENCY_PER_ACCOUNT = 2

# 错误冷却基础时间（秒），指数退避：base * 2^(consecutive_errors - 1)
ERROR_COOLDOWN_BASE = 30.0

# 最大冷却时间（秒）
MAX_COOLDOWN = 600.0

# 连续错误 N 次后标记账号为不可用
MAX_CONSECUTIVE_ERRORS = 5

# 账号不可用后的恢复检测间隔（秒）
RECOVERY_CHECK_INTERVAL = 300.0

# 健康权重衰减：每次错误权重降低的比例
WEIGHT_DECAY_ON_ERROR = 0.5

# 健康权重恢复：每次成功权重恢复的比例
WEIGHT_RECOVERY_ON_SUCCESS = 0.2


# ─── 账号状态 ─────────────────────────────────────────────────

@dataclass
class AccountState:
    """单个账号的运行时状态"""
    account: MimoAccount
    index: int  # 在配置列表中的位置

    # 频率控制
    last_request_time: float = 0.0

    # 并发控制
    active_requests: int = 0

    # 错误退避
    consecutive_errors: int = 0
    last_error_time: float = 0.0
    cooldown_until: float = 0.0

    # 健康权重 (0.0 ~ 1.0)
    weight: float = 1.0

    # 统计
    total_requests: int = 0
    total_successes: int = 0
    total_errors: int = 0

    # 是否被标记为不可用
    disabled: bool = False
    disabled_until: float = 0.0

    @property
    def is_available(self) -> bool:
        """账号当前是否可用"""
        now = time.time()

        # 被禁用且未到恢复时间
        if self.disabled and now < self.disabled_until:
            return False

        # 在冷却期内
        if now < self.cooldown_until:
            return False

        # 并发数已满
        if self.active_requests >= MAX_CONCURRENCY_PER_ACCOUNT:
            return False

        # 请求间隔不足
        if now - self.last_request_time < MIN_REQUEST_INTERVAL:
            return False

        return True

    @property
    def effective_weight(self) -> float:
        """有效权重（考虑各种因素）"""
        if not self.is_available:
            return 0.0
        return max(0.01, self.weight)

    @property
    def wait_time(self) -> float:
        """距离可用还需等待的时间（秒）"""
        now = time.time()
        waits = []

        if self.disabled and now < self.disabled_until:
            waits.append(self.disabled_until - now)
        if now < self.cooldown_until:
            waits.append(self.cooldown_until - now)
        if now - self.last_request_time < MIN_REQUEST_INTERVAL:
            waits.append(MIN_REQUEST_INTERVAL - (now - self.last_request_time))

        return max(waits) if waits else 0.0


# ─── 智能调度器 ───────────────────────────────────────────────

class AccountPool:
    """智能账号池调度器

    使用加权随机选择 + 频率控制 + 错误退避实现防风控轮询。
    """

    def __init__(self):
        self._states: List[AccountState] = []
        self._lock = threading.RLock()
        self._initialized = False

    def init_pool(self, accounts: List[MimoAccount]) -> None:
        """初始化账号池（配置加载/更新时调用）"""
        with self._lock:
            # 保留已有状态（如果账号没变的话）
            old_states = {s.account.user_id: s for s in self._states}
            new_states = []
            for i, acc in enumerate(accounts):
                if acc.user_id in old_states:
                    # 保留运行时状态，更新账号信息和索引
                    state = old_states[acc.user_id]
                    state.account = acc
                    state.index = i
                    new_states.append(state)
                else:
                    new_states.append(AccountState(account=acc, index=i))
            self._states = new_states
            self._initialized = True

    def acquire_account(self) -> Optional[MimoAccount]:
        """获取下一个可用账号

        选择策略：
        1. 过滤掉不可用的账号
        2. 按权重加权随机选择（避免单一账号被集中使用）
        3. 如果所有账号都不可用，返回等待时间最短的那个（阻塞等待）

        Returns:
            MimoAccount 或 None（无可用账号）
        """
        with self._lock:
            if not self._states:
                return None

            # 尝试选择可用账号
            available = [s for s in self._states if s.is_available]

            if available:
                account_state = self._weighted_select(available)
            else:
                # 所有账号都不可用，选择等待时间最短的（排除永久禁用的）
                recoverable = [s for s in self._states
                               if not s.disabled or time.time() >= s.disabled_until]
                if not recoverable:
                    # 尝试恢复被禁用的账号
                    recoverable = self._states
                account_state = min(recoverable, key=lambda s: s.wait_time)

            # 标记为使用中
            account_state.active_requests += 1
            account_state.last_request_time = time.time()
            account_state.total_requests += 1

            return account_state.account

    def release_account(self, account: MimoAccount, success: bool = True,
                        error_code: int = None) -> None:
        """释放账号（请求完成后调用）

        Args:
            account: 使用的账号
            success: 请求是否成功
            error_code: HTTP 错误码（如 429、403 等触发更严格的冷却）
        """
        with self._lock:
            state = self._find_state(account)
            if not state:
                return

            state.active_requests = max(0, state.active_requests - 1)

            if success:
                self._on_success(state)
            else:
                self._on_error(state, error_code)

    def get_pool_status(self) -> dict:
        """获取账号池状态（用于管理面板展示）"""
        with self._lock:
            now = time.time()
            accounts_status = []
            for s in self._states:
                accounts_status.append({
                    "user_id": s.account.user_id,
                    "index": s.index,
                    "available": s.is_available,
                    "weight": round(s.weight, 3),
                    "active_requests": s.active_requests,
                    "consecutive_errors": s.consecutive_errors,
                    "cooldown_remaining": max(0, round(s.cooldown_until - now, 1)),
                    "disabled": s.disabled,
                    "total_requests": s.total_requests,
                    "total_successes": s.total_successes,
                    "total_errors": s.total_errors,
                    "success_rate": round(
                        s.total_successes / s.total_requests * 100, 1
                    ) if s.total_requests > 0 else 100.0,
                    "last_request_time": s.last_request_time,
                })
            return {
                "total_accounts": len(self._states),
                "available_accounts": sum(1 for s in self._states if s.is_available),
                "accounts": accounts_status,
                "config": {
                    "min_request_interval": MIN_REQUEST_INTERVAL,
                    "max_concurrency_per_account": MAX_CONCURRENCY_PER_ACCOUNT,
                    "error_cooldown_base": ERROR_COOLDOWN_BASE,
                    "max_cooldown": MAX_COOLDOWN,
                    "max_consecutive_errors": MAX_CONSECUTIVE_ERRORS,
                }
            }

    def reset_account(self, user_id: str) -> bool:
        """手动重置账号状态（管理面板用）"""
        with self._lock:
            for s in self._states:
                if s.account.user_id == user_id:
                    s.consecutive_errors = 0
                    s.cooldown_until = 0.0
                    s.weight = 1.0
                    s.disabled = False
                    s.disabled_until = 0.0
                    return True
            return False

    # ─── 内部方法 ─────────────────────────────────────────────

    def _weighted_select(self, available: List[AccountState]) -> AccountState:
        """加权随机选择

        权重高的账号被选中的概率更大，但不会完全排除低权重账号，
        保证请求分散到所有可用账号。
        """
        weights = [s.effective_weight for s in available]
        total = sum(weights)
        if total == 0:
            return random.choice(available)

        # 加权随机
        r = random.uniform(0, total)
        cumulative = 0.0
        for s, w in zip(available, weights):
            cumulative += w
            if r <= cumulative:
                return s
        return available[-1]

    def _find_state(self, account: MimoAccount) -> Optional[AccountState]:
        """通过 user_id 查找账号状态"""
        for s in self._states:
            if s.account.user_id == account.user_id:
                return s
        return None

    def _on_success(self, state: AccountState) -> None:
        """请求成功的处理"""
        state.total_successes += 1
        state.consecutive_errors = 0

        # 权重恢复（向 1.0 靠拢）
        if state.weight < 1.0:
            state.weight = min(1.0, state.weight + WEIGHT_RECOVERY_ON_SUCCESS)

        # 如果之前被禁用，恢复之
        if state.disabled:
            state.disabled = False
            state.disabled_until = 0.0
            print(f"[AccountPool] 账号 {state.account.user_id} 已恢复正常")

    def _on_error(self, state: AccountState, error_code: int = None) -> None:
        """请求失败的处理"""
        now = time.time()
        state.total_errors += 1
        state.consecutive_errors += 1
        state.last_error_time = now

        # 权重衰减
        state.weight = max(0.01, state.weight * WEIGHT_DECAY_ON_ERROR)

        # 计算冷却时间
        cooldown = self._calc_cooldown(state.consecutive_errors, error_code)
        state.cooldown_until = now + cooldown

        print(f"[AccountPool] 账号 {state.account.user_id} 请求失败 "
              f"(连续第{state.consecutive_errors}次), "
              f"冷却 {cooldown:.0f}s, 权重 {state.weight:.3f}")

        # 连续错误过多 → 禁用
        if state.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            state.disabled = True
            state.disabled_until = now + RECOVERY_CHECK_INTERVAL
            print(f"[AccountPool] 账号 {state.account.user_id} 已被禁用, "
                  f"{RECOVERY_CHECK_INTERVAL:.0f}s 后尝试恢复")

    def _calc_cooldown(self, consecutive_errors: int, error_code: int = None) -> float:
        """计算冷却时间（指数退避）"""
        base = ERROR_COOLDOWN_BASE

        # 特殊错误码给更长冷却
        if error_code == 429:  # Too Many Requests
            base *= 3
        elif error_code == 403:  # Forbidden（可能被封）
            base *= 5
        elif error_code == 401:  # Unauthorized（token 失效）
            base *= 10

        cooldown = base * (2 ** (consecutive_errors - 1))
        return min(cooldown, MAX_COOLDOWN)


# ─── 全局单例 ─────────────────────────────────────────────────

account_pool = AccountPool()
