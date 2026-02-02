#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APIPod 账号池管理器
==================
实现账号轮询、健康检查、负载均衡等功能
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum
from openai import OpenAI


class AccountStatus(Enum):
    """账号状态"""
    ACTIVE = "active"              # 活跃可用
    INACTIVE = "inactive"          # 未激活
    RATE_LIMITED = "rate_limited"  # 速率限制
    BANNED = "banned"              # 被封禁
    ERROR = "error"                # 错误状态


@dataclass
class Account:
    """账号数据类"""
    username: str
    email: str
    password: str
    api_key: str
    base_url: str = "https://api.apipod.ai/v1"
    status: str = "active"
    created_at: str = ""
    last_used: str = ""
    request_count: int = 0
    error_count: int = 0
    consecutive_errors: int = 0
    avg_response_time: float = 0.0
    success_rate: float = 100.0
    total_requests: int = 0
    success_count: int = 0
    cooldown_until: float = 0.0
    group: str = "default"
    daily_requests: Dict[str, int] = None
    model_usage: Dict[str, int] = None
    total_tokens: int = 0
    total_cost: float = 0.0

    def __post_init__(self):
        if self.daily_requests is None:
            self.daily_requests = {}
        if self.model_usage is None:
            self.model_usage = {}
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def is_cooling(self) -> bool:
        """检查是否在冷却期"""
        return time.time() < self.cooldown_until

    def set_cooldown(self, seconds: int = 60):
        """设置冷却时间"""
        self.cooldown_until = time.time() + seconds

    def update_stats(self, success: bool, response_time: float = 0):
        """更新统计信息"""
        self.total_requests += 1
        self.request_count += 1
        self.last_used = datetime.now().isoformat()

        if success:
            self.success_count += 1
            self.consecutive_errors = 0
            # 更新平均响应时间
            if self.avg_response_time == 0:
                self.avg_response_time = response_time
            else:
                self.avg_response_time = (self.avg_response_time * 0.9 + response_time * 0.1)
        else:
            self.error_count += 1
            self.consecutive_errors += 1

        # 更新成功率
        if self.total_requests > 0:
            self.success_rate = (self.success_count / self.total_requests) * 100

        # 更新每日请求统计
        today = datetime.now().strftime("%Y-%m-%d")
        self.daily_requests[today] = self.daily_requests.get(today, 0) + 1

    def to_dict(self) -> dict:
        """转换为字典"""
        data = asdict(self)
        data['status'] = self.status
        return data


class AccountPool:
    """账号池管理器"""

    def __init__(self, pool_file: str = "account_pool.json"):
        self.pool_file = pool_file
        self.accounts: Dict[str, Account] = {}
        self._active_list: List[str] = []
        self._current_index = 0
        self._lock = asyncio.Lock()

    def load(self):
        """从文件加载账号池"""
        try:
            with open(self.pool_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for acc_data in data.get('accounts', []):
                    acc = Account(**acc_data)
                    self.accounts[acc.email] = acc
            self._refresh_active_list()
            print(f"[加载] 成功加载 {len(self.accounts)} 个账号")
        except FileNotFoundError:
            print(f"[加载] 账号池文件不存在，将创建新文件")
            self.save()
        except Exception as e:
            print(f"[加载] 加载失败: {e}")

    def save(self):
        """保存账号池到文件"""
        try:
            data = {
                "updated_at": datetime.now().isoformat(),
                "accounts": [acc.to_dict() for acc in self.accounts.values()]
            }
            with open(self.pool_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[保存] 保存失败: {e}")

    def _refresh_active_list(self):
        """刷新活跃账号列表"""
        self._active_list = [
            email for email, acc in self.accounts.items()
            if acc.status == AccountStatus.ACTIVE.value and not acc.is_cooling()
        ]
        print(f"[刷新] 活跃账号: {len(self._active_list)}/{len(self.accounts)}")

    def add_account(self, account: Account):
        """添加账号到池中"""
        self.accounts[account.email] = account
        self._refresh_active_list()
        self.save()
        print(f"[添加] 账号 {account.email} 已添加")

    def remove_account(self, email: str):
        """从池中移除账号"""
        if email in self.accounts:
            del self.accounts[email]
            self._refresh_active_list()
            self.save()
            print(f"[移除] 账号 {email} 已移除")

    async def get_next_account(self) -> Optional[Account]:
        """获取下一个可用账号（轮询）"""
        async with self._lock:
            self._refresh_active_list()

            if not self._active_list:
                print("[轮询] 没有可用账号")
                return None

            # 轮询选择
            email = self._active_list[self._current_index % len(self._active_list)]
            self._current_index += 1

            return self.accounts[email]

    async def chat(self, message: str, model: str = "gpt-4o-mini") -> dict:
        """使用账号池发送聊天请求"""
        account = await self.get_next_account()
        if not account:
            return {"error": "没有可用账号"}

        start_time = time.time()
        try:
            client = OpenAI(
                base_url=account.base_url,
                api_key=account.api_key
            )

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": message}]
            )

            response_time = time.time() - start_time
            result = response.choices[0].message.content

            # 更新统计
            account.update_stats(success=True, response_time=response_time)
            account.model_usage[model] = account.model_usage.get(model, 0) + 1

            # 更新 token 统计
            if hasattr(response, 'usage'):
                account.total_tokens += response.usage.total_tokens

            self.save()

            return {
                "success": True,
                "response": result,
                "account": account.email,
                "model": model,
                "response_time": round(response_time, 2)
            }

        except Exception as e:
            response_time = time.time() - start_time
            account.update_stats(success=False, response_time=response_time)

            # 连续错误处理
            if account.consecutive_errors >= 3:
                account.status = AccountStatus.ERROR.value
                account.set_cooldown(300)  # 冷却 5 分钟
                print(f"[错误] 账号 {account.email} 连续失败，进入冷却")

            self.save()

            return {
                "success": False,
                "error": str(e),
                "account": account.email,
                "response_time": round(response_time, 2)
            }

    async def health_check(self, email: str) -> bool:
        """健康检查单个账号"""
        if email not in self.accounts:
            return False

        account = self.accounts[email]
        try:
            client = OpenAI(
                base_url=account.base_url,
                api_key=account.api_key
            )

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5
            )

            account.status = AccountStatus.ACTIVE.value
            account.consecutive_errors = 0
            print(f"[健康检查] {email} - 正常")
            return True

        except Exception as e:
            account.status = AccountStatus.ERROR.value
            print(f"[健康检查] {email} - 失败: {e}")
            return False
        finally:
            self.save()

    async def health_check_all(self, concurrent: int = 5):
        """批量健康检查所有账号"""
        print(f"\n[健康检查] 开始检查 {len(self.accounts)} 个账号...")

        emails = list(self.accounts.keys())
        results = {"success": 0, "failed": 0}

        # 分批并发检查
        for i in range(0, len(emails), concurrent):
            batch = emails[i:i + concurrent]
            tasks = [self.health_check(email) for email in batch]
            batch_results = await asyncio.gather(*tasks)

            for success in batch_results:
                if success:
                    results["success"] += 1
                else:
                    results["failed"] += 1

        self._refresh_active_list()
        print(f"[健康检查] 完成 - 成功: {results['success']}, 失败: {results['failed']}")
        return results

    def get_stats(self) -> dict:
        """获取统计信息"""
        total = len(self.accounts)
        active = len(self._active_list)

        status_count = {}
        for acc in self.accounts.values():
            status_count[acc.status] = status_count.get(acc.status, 0) + 1

        total_requests = sum(acc.total_requests for acc in self.accounts.values())
        total_success = sum(acc.success_count for acc in self.accounts.values())
        avg_success_rate = (total_success / total_requests * 100) if total_requests > 0 else 0

        return {
            "total": total,
            "active": active,
            "inactive": status_count.get("inactive", 0),
            "rate_limited": status_count.get("rate_limited", 0),
            "banned": status_count.get("banned", 0),
            "error": status_count.get("error", 0),
            "cooling": sum(1 for acc in self.accounts.values() if acc.is_cooling()),
            "total_requests": total_requests,
            "success_rate": round(avg_success_rate, 2),
            "avg_response_time": round(
                sum(acc.avg_response_time for acc in self.accounts.values()) / total, 2
            ) if total > 0 else 0
        }

    def list_accounts(self, status_filter: Optional[str] = None) -> List[dict]:
        """列出账号"""
        accounts = []
        for acc in self.accounts.values():
            if status_filter and acc.status != status_filter:
                continue

            accounts.append({
                "email": acc.email,
                "username": acc.username,
                "status": acc.status,
                "request_count": acc.request_count,
                "error_count": acc.error_count,
                "success_rate": round(acc.success_rate, 1),
                "avg_response_time": round(acc.avg_response_time, 2),
                "last_used": acc.last_used,
                "is_cooling": acc.is_cooling(),
                "group": acc.group
            })

        return accounts


# ========== 便捷函数 ==========

async def import_from_json(pool: AccountPool, json_file: str):
    """从 batch_register 生成的 JSON 导入账号"""
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        imported = 0
        for item in data:
            if not item.get('success'):
                continue

            account = Account(
                username=item['username'],
                email=item['email'],
                password=item['password'],
                api_key=item['api_key'],
                base_url=item['base_url'],
                status=AccountStatus.ACTIVE.value,
                created_at=item.get('created_at', datetime.now().isoformat())
            )

            pool.add_account(account)
            imported += 1

        print(f"[导入] 成导入 {imported} 个账号")
        return imported

    except Exception as e:
        print(f"[导入] 导入失败: {e}")
        return 0


# ========== 命令行接口 ==========

async def main():
    import argparse

    parser = argparse.ArgumentParser(description='APIPod 账号池管理器')
    parser.add_argument('--pool-file', default='account_pool.json', help='账号池文件路径')

    subparsers = parser.add_subparsers(dest='command', help='命令')

    # 导入命令
    import_parser = subparsers.add_parser('import', help='导入账号')
    import_parser.add_argument('json_file', help='accounts.json 文件路径')

    # 列表命令
    list_parser = subparsers.add_parser('list', help='列出账号')
    list_parser.add_argument('--status', help='按状态过滤')

    # 统计命令
    subparsers.add_parser('stats', help='显示统计信息')

    # 健康检查命令
    health_parser = subparsers.add_parser('health', help='健康检查')
    health_parser.add_argument('--concurrent', type=int, default=5, help='并发数')

    # 聊天测试命令
    chat_parser = subparsers.add_parser('chat', help='测试聊天')
    chat_parser.add_argument('message', help='消息内容')
    chat_parser.add_argument('--model', default='gpt-4o-mini', help='模型名称')

    args = parser.parse_args()

    # 创建账号池
    pool = AccountPool(args.pool_file)
    pool.load()

    if args.command == 'import':
        await import_from_json(pool, args.json_file)

    elif args.command == 'list':
        accounts = pool.list_accounts(args.status)
        print(f"\n共 {len(accounts)} 个账号:\n")
        for acc in accounts:
            print(f"  {acc['email']}")
            print(f"    状态: {acc['status']}")
            print(f"    请求: {acc['request_count']}, 成功率: {acc['success_rate']}%")
            print(f"    响应时间: {acc['avg_response_time']}s")
            print()

    elif args.command == 'stats':
        stats = pool.get_stats()
        print("\n=== 账号池统计 ===")
        print(f"总账号数: {stats['total']}")
        print(f"活跃账号: {stats['active']}")
        print(f"错误账号: {stats['error']}")
        print(f"冷却账号: {stats['cooling']}")
        print(f"总请求数: {stats['total_requests']}")
        print(f"成功率: {stats['success_rate']}%")
        print(f"平均响应时间: {stats['avg_response_time']}s")

    elif args.command == 'health':
        await pool.health_check_all(args.concurrent)

    elif args.command == 'chat':
        result = await pool.chat(args.message, args.model)
        if result.get('success'):
            print(f"\n[{result['account']}] {result['response']}")
            print(f"响应时间: {result['response_time']}s")
        else:
            print(f"\n[错误] {result.get('error')}")

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
