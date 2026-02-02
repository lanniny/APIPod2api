#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APIPod 统一网关服务器
====================
提供 OpenAI 兼容 API + Web UI 管理界面
"""

import asyncio
import json
import time
import uuid
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional
from aiohttp import web
from pool_manager import AccountPool, Account, AccountStatus, import_from_json
from openai import OpenAI


# ============ 用户认证系统 ============

class AuthManager:
    """用户认证管理"""

    def __init__(self, users_file: str = "users.json"):
        self.users_file = users_file
        self.users = {}
        self.sessions = {}  # token -> {username, expires}
        self.load()

    def load(self):
        """加载用户数据"""
        if os.path.exists(self.users_file):
            with open(self.users_file, 'r', encoding='utf-8') as f:
                self.users = json.load(f)
        else:
            # 创建默认管理员账号
            self.users = {
                "admin": {
                    "password_hash": self._hash_password("admin123"),
                    "role": "admin",
                    "created_at": datetime.now().isoformat()
                }
            }
            self.save()
            print("[Auth] Created default admin account: admin / admin123")

    def save(self):
        """保存用户数据"""
        with open(self.users_file, 'w', encoding='utf-8') as f:
            json.dump(self.users, f, indent=2, ensure_ascii=False)

    def _hash_password(self, password: str) -> str:
        """哈希密码"""
        return hashlib.sha256(password.encode()).hexdigest()

    def verify_password(self, username: str, password: str) -> bool:
        """验证密码"""
        if username not in self.users:
            return False
        return self.users[username]["password_hash"] == self._hash_password(password)

    def create_session(self, username: str) -> str:
        """创建会话token"""
        token = secrets.token_urlsafe(32)
        self.sessions[token] = {
            "username": username,
            "expires": (datetime.now() + timedelta(hours=24)).isoformat()
        }
        return token

    def verify_session(self, token: str) -> Optional[str]:
        """验证会话，返回用户名或None"""
        if not token or token not in self.sessions:
            return None
        session = self.sessions[token]
        if datetime.fromisoformat(session["expires"]) < datetime.now():
            del self.sessions[token]
            return None
        return session["username"]

    def logout(self, token: str):
        """登出"""
        if token in self.sessions:
            del self.sessions[token]

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        """修改密码"""
        if not self.verify_password(username, old_password):
            return False
        self.users[username]["password_hash"] = self._hash_password(new_password)
        self.save()
        return True

    def add_user(self, username: str, password: str, role: str = "user") -> bool:
        """添加用户"""
        if username in self.users:
            return False
        self.users[username] = {
            "password_hash": self._hash_password(password),
            "role": role,
            "created_at": datetime.now().isoformat()
        }
        self.save()
        return True

    def delete_user(self, username: str) -> bool:
        """删除用户"""
        if username not in self.users or username == "admin":
            return False
        del self.users[username]
        self.save()
        return True

    def list_users(self) -> list:
        """列出所有用户"""
        return [{"username": k, "role": v["role"], "created_at": v["created_at"]}
                for k, v in self.users.items()]


# ============ 网关 Key 管理 ============

class GatewayKeyManager:
    """网关 API Key 管理"""

    def __init__(self, config_file: str = "gateway_config.json"):
        self.config_file = config_file
        self.config = {
            "api_keys": [],  # 允许的 API Keys 列表
            "require_key": False,  # 是否需要验证 Key
            "allow_any_key": True  # 是否允许任意 Key（兼容模式）
        }
        self.load()

    def load(self):
        """加载配置"""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                self.config.update(saved)
        else:
            # 生成默认 Key
            default_key = "sk-" + secrets.token_hex(24)
            self.config["api_keys"] = [
                {"key": default_key, "name": "Default Key", "created_at": datetime.now().isoformat()}
            ]
            self.save()
            print(f"[Gateway] Created default API key: {default_key}")

    def save(self):
        """保存配置"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    def verify_key(self, key: str) -> bool:
        """验证 API Key"""
        if not key:
            return False
        # 兼容模式：允许任意 Key
        if self.config.get("allow_any_key", True):
            return True
        # 严格模式：验证 Key 列表
        for k in self.config["api_keys"]:
            if k["key"] == key:
                return True
        return False

    def add_key(self, name: str = "New Key") -> dict:
        """添加新 Key"""
        new_key = "sk-" + secrets.token_hex(24)
        key_obj = {
            "key": new_key,
            "name": name,
            "created_at": datetime.now().isoformat()
        }
        self.config["api_keys"].append(key_obj)
        self.save()
        return key_obj

    def delete_key(self, key: str) -> bool:
        """删除 Key"""
        for i, k in enumerate(self.config["api_keys"]):
            if k["key"] == key:
                self.config["api_keys"].pop(i)
                self.save()
                return True
        return False

    def list_keys(self) -> list:
        """列出所有 Key（部分隐藏）"""
        return [{
            "key": k["key"][:12] + "..." + k["key"][-4:],
            "full_key": k["key"],
            "name": k["name"],
            "created_at": k["created_at"]
        } for k in self.config["api_keys"]]

    def get_settings(self) -> dict:
        """获取设置"""
        return {
            "require_key": self.config.get("require_key", False),
            "allow_any_key": self.config.get("allow_any_key", True),
            "key_count": len(self.config["api_keys"])
        }

    def update_settings(self, require_key: bool = None, allow_any_key: bool = None):
        """更新设置"""
        if require_key is not None:
            self.config["require_key"] = require_key
        if allow_any_key is not None:
            self.config["allow_any_key"] = allow_any_key
        self.save()

# ============ OpenAI 兼容网关 ============

class APIGateway:
    """OpenAI 兼容 API 网关"""

    def __init__(self, pool: AccountPool):
        self.pool = pool
        self.request_log: list = []
        self.max_log = 1000

    def _log_request(self, method: str, model: str, account: str, success: bool, response_time: float, error: str = ""):
        """记录请求日志"""
        self.request_log.append({
            "id": str(uuid.uuid4())[:8],
            "time": datetime.now().isoformat(),
            "method": method,
            "model": model,
            "account": account,
            "success": success,
            "response_time": round(response_time, 2),
            "error": error
        })
        if len(self.request_log) > self.max_log:
            self.request_log = self.request_log[-self.max_log:]

    async def handle_chat_completions(self, request: web.Request) -> web.StreamResponse:
        """处理 /v1/chat/completions 请求"""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": {"message": "Invalid JSON", "type": "invalid_request_error"}}, status=400)

        model = body.get("model", "gpt-4o-mini")
        messages = body.get("messages", [])
        stream = body.get("stream", False)
        temperature = body.get("temperature", 1.0)
        max_tokens = body.get("max_tokens")
        top_p = body.get("top_p", 1.0)

        if not messages:
            return web.json_response({"error": {"message": "messages is required", "type": "invalid_request_error"}}, status=400)

        # 获取下一个可用账号
        account = await self.pool.get_next_account()
        if not account:
            return web.json_response({"error": {"message": "No available account in pool", "type": "server_error"}}, status=503)

        start_time = time.time()

        try:
            client = OpenAI(base_url=account.base_url, api_key=account.api_key)
            params = {"model": model, "messages": messages, "temperature": temperature, "top_p": top_p}
            if max_tokens:
                params["max_tokens"] = max_tokens

            if stream:
                return await self._handle_stream(request, client, params, account, start_time)
            else:
                return await self._handle_sync(client, params, account, start_time)

        except Exception as e:
            response_time = time.time() - start_time
            account.update_stats(success=False, response_time=response_time)
            if account.consecutive_errors >= 3:
                account.status = AccountStatus.ERROR.value
                account.set_cooldown(300)
            self.pool.save()
            self._log_request("chat.completions", model, account.email, False, response_time, str(e))

            return web.json_response({
                "error": {"message": str(e), "type": "api_error"}
            }, status=502)

    async def _handle_sync(self, client, params, account, start_time) -> web.Response:
        """处理同步请求"""
        response = client.chat.completions.create(**params, stream=False)
        response_time = time.time() - start_time

        account.update_stats(success=True, response_time=response_time)
        model = params["model"]
        account.model_usage[model] = account.model_usage.get(model, 0) + 1
        if hasattr(response, 'usage') and response.usage:
            account.total_tokens += response.usage.total_tokens
        self.pool.save()
        self._log_request("chat.completions", model, account.email, True, response_time)

        return web.json_response(response.model_dump())

    async def _handle_stream(self, request, client, params, account, start_time) -> web.StreamResponse:
        """处理流式请求"""
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With"
            }
        )
        await response.prepare(request)

        try:
            stream = client.chat.completions.create(**params, stream=True)
            for chunk in stream:
                data = json.dumps(chunk.model_dump(), ensure_ascii=False)
                await response.write(f"data: {data}\n\n".encode("utf-8"))

            await response.write(b"data: [DONE]\n\n")

            response_time = time.time() - start_time
            account.update_stats(success=True, response_time=response_time)
            model = params["model"]
            account.model_usage[model] = account.model_usage.get(model, 0) + 1
            self.pool.save()
            self._log_request("chat.completions.stream", model, account.email, True, response_time)

        except Exception as e:
            response_time = time.time() - start_time
            account.update_stats(success=False, response_time=response_time)
            self.pool.save()
            self._log_request("chat.completions.stream", params["model"], account.email, False, response_time, str(e))
            error_data = json.dumps({"error": {"message": str(e)}})
            await response.write(f"data: {error_data}\n\n".encode("utf-8"))

        return response

    async def handle_models(self, request: web.Request) -> web.Response:
        """处理 /v1/models 请求 - 代理到 APIPod 获取实际模型列表"""
        # 获取一个可用账号来查询模型
        account = await self.pool.get_next_account()
        if not account:
            # 如果没有账号，返回基本模型列表
            models = [
                {"id": "gpt-4o-mini", "object": "model", "created": 1700000000, "owned_by": "openai"},
                {"id": "gpt-4o", "object": "model", "created": 1700000000, "owned_by": "openai"},
                {"id": "gpt-5", "object": "model", "created": 1700000000, "owned_by": "openai"},
                {"id": "claude-sonnet-4-5", "object": "model", "created": 1700000000, "owned_by": "anthropic"},
            ]
            return web.json_response({"object": "list", "data": models})

        try:
            client = OpenAI(base_url=account.base_url, api_key=account.api_key)
            models_response = client.models.list()
            models_data = [m.model_dump() for m in models_response.data]
            return web.json_response({"object": "list", "data": models_data})
        except Exception as e:
            # 出错时返回基本列表
            models = [
                {"id": "gpt-4o-mini", "object": "model", "created": 1700000000, "owned_by": "openai"},
                {"id": "gpt-4o", "object": "model", "created": 1700000000, "owned_by": "openai"},
                {"id": "gpt-5", "object": "model", "created": 1700000000, "owned_by": "openai"},
                {"id": "claude-sonnet-4-5", "object": "model", "created": 1700000000, "owned_by": "anthropic"},
            ]
            return web.json_response({"object": "list", "data": models})


# ============ Web UI API ============

class WebAPI:
    """Web 管理 API"""

    def __init__(self, pool: AccountPool, gateway: APIGateway):
        self.pool = pool
        self.gateway = gateway

    async def get_dashboard(self, request: web.Request) -> web.Response:
        """获取仪表盘数据"""
        stats = self.pool.get_stats()
        stats["recent_logs"] = self.gateway.request_log[-20:][::-1]
        return web.json_response(stats)

    async def get_accounts(self, request: web.Request) -> web.Response:
        """获取账号列表"""
        status = request.query.get("status")
        accounts = self.pool.list_accounts(status)
        return web.json_response({"accounts": accounts, "total": len(accounts)})

    async def get_account_detail(self, request: web.Request) -> web.Response:
        """获取单个账号详情"""
        email = request.match_info.get("email")
        if email not in self.pool.accounts:
            return web.json_response({"error": "Account not found"}, status=404)
        acc = self.pool.accounts[email]
        return web.json_response(acc.to_dict())

    async def add_account(self, request: web.Request) -> web.Response:
        """手动添加账号"""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        required = ["email", "password", "api_key"]
        for field in required:
            if field not in body:
                return web.json_response({"error": f"Missing field: {field}"}, status=400)

        account = Account(
            username=body.get("username", body["email"].split("@")[0]),
            email=body["email"],
            password=body["password"],
            api_key=body["api_key"],
            base_url=body.get("base_url", "https://api.apipod.ai/v1"),
            group=body.get("group", "default")
        )
        self.pool.add_account(account)
        return web.json_response({"success": True, "message": f"Account {account.email} added"})

    async def delete_account(self, request: web.Request) -> web.Response:
        """删除账号"""
        email = request.match_info.get("email")
        if email not in self.pool.accounts:
            return web.json_response({"error": "Account not found"}, status=404)
        self.pool.remove_account(email)
        return web.json_response({"success": True, "message": f"Account {email} removed"})

    async def toggle_account(self, request: web.Request) -> web.Response:
        """切换账号状态"""
        email = request.match_info.get("email")
        if email not in self.pool.accounts:
            return web.json_response({"error": "Account not found"}, status=404)

        acc = self.pool.accounts[email]
        if acc.status == AccountStatus.ACTIVE.value:
            acc.status = AccountStatus.INACTIVE.value
        else:
            acc.status = AccountStatus.ACTIVE.value
            acc.consecutive_errors = 0
            acc.cooldown_until = 0

        self.pool._refresh_active_list()
        self.pool.save()
        return web.json_response({"success": True, "status": acc.status})

    async def health_check_account(self, request: web.Request) -> web.Response:
        """健康检查单个账号"""
        email = request.match_info.get("email")
        result = await self.pool.health_check(email)
        acc = self.pool.accounts.get(email)
        return web.json_response({
            "success": result,
            "status": acc.status if acc else "unknown"
        })

    async def health_check_all(self, request: web.Request) -> web.Response:
        """健康检查所有账号"""
        results = await self.pool.health_check_all()
        return web.json_response(results)

    async def import_accounts(self, request: web.Request) -> web.Response:
        """从 JSON 文件导入账号"""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        accounts_data = body.get("accounts", [])
        imported = 0
        for item in accounts_data:
            if not item.get("api_key"):
                continue
            account = Account(
                username=item.get("username", ""),
                email=item.get("email", ""),
                password=item.get("password", ""),
                api_key=item["api_key"],
                base_url=item.get("base_url", "https://api.apipod.ai/v1"),
                status=AccountStatus.ACTIVE.value,
                created_at=item.get("created_at", datetime.now().isoformat())
            )
            self.pool.add_account(account)
            imported += 1

        return web.json_response({"success": True, "imported": imported})

    async def get_request_logs(self, request: web.Request) -> web.Response:
        """获取请求日志"""
        limit = int(request.query.get("limit", 50))
        logs = self.gateway.request_log[-limit:][::-1]
        return web.json_response({"logs": logs, "total": len(self.gateway.request_log)})

    async def batch_register(self, request: web.Request) -> web.Response:
        """触发批量注册"""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        count = body.get("count", 5)
        suffix = body.get("suffix", "tmpmail.net")

        # 返回注册已启动的响应，实际注册在后台进行
        return web.json_response({
            "success": True,
            "message": f"Batch registration started: {count} accounts with suffix @{suffix}",
            "hint": "Use the CLI: python batch_register.py --count {count} --suffix {suffix}"
        })


# ============ 认证 API ============

class AuthAPI:
    """认证相关 API"""

    def __init__(self, auth_manager: AuthManager):
        self.auth = auth_manager

    async def login(self, request: web.Request) -> web.Response:
        """登录"""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        username = body.get("username", "")
        password = body.get("password", "")

        if not self.auth.verify_password(username, password):
            return web.json_response({"error": "Invalid username or password"}, status=401)

        token = self.auth.create_session(username)
        response = web.json_response({
            "success": True,
            "token": token,
            "username": username,
            "role": self.auth.users[username]["role"]
        })
        response.set_cookie("auth_token", token, max_age=86400, httponly=True, samesite="Lax")
        return response

    async def logout(self, request: web.Request) -> web.Response:
        """登出"""
        token = request.cookies.get("auth_token") or request.headers.get("X-Auth-Token", "")
        self.auth.logout(token)
        response = web.json_response({"success": True})
        response.del_cookie("auth_token")
        return response

    async def check_auth(self, request: web.Request) -> web.Response:
        """检查登录状态"""
        token = request.cookies.get("auth_token") or request.headers.get("X-Auth-Token", "")
        username = self.auth.verify_session(token)
        if not username:
            return web.json_response({"authenticated": False}, status=401)
        return web.json_response({
            "authenticated": True,
            "username": username,
            "role": self.auth.users[username]["role"]
        })

    async def change_password(self, request: web.Request) -> web.Response:
        """修改密码"""
        token = request.cookies.get("auth_token") or request.headers.get("X-Auth-Token", "")
        username = self.auth.verify_session(token)
        if not username:
            return web.json_response({"error": "Not authenticated"}, status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        old_password = body.get("old_password", "")
        new_password = body.get("new_password", "")

        if len(new_password) < 6:
            return web.json_response({"error": "Password must be at least 6 characters"}, status=400)

        if not self.auth.change_password(username, old_password, new_password):
            return web.json_response({"error": "Invalid old password"}, status=400)

        return web.json_response({"success": True})

    async def list_users(self, request: web.Request) -> web.Response:
        """列出用户（仅管理员）"""
        token = request.cookies.get("auth_token") or request.headers.get("X-Auth-Token", "")
        username = self.auth.verify_session(token)
        if not username or self.auth.users[username]["role"] != "admin":
            return web.json_response({"error": "Admin access required"}, status=403)
        return web.json_response({"users": self.auth.list_users()})

    async def add_user(self, request: web.Request) -> web.Response:
        """添加用户（仅管理员）"""
        token = request.cookies.get("auth_token") or request.headers.get("X-Auth-Token", "")
        username = self.auth.verify_session(token)
        if not username or self.auth.users[username]["role"] != "admin":
            return web.json_response({"error": "Admin access required"}, status=403)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        new_username = body.get("username", "")
        new_password = body.get("password", "")
        role = body.get("role", "user")

        if not new_username or not new_password:
            return web.json_response({"error": "Username and password required"}, status=400)

        if not self.auth.add_user(new_username, new_password, role):
            return web.json_response({"error": "User already exists"}, status=400)

        return web.json_response({"success": True})

    async def delete_user(self, request: web.Request) -> web.Response:
        """删除用户（仅管理员）"""
        token = request.cookies.get("auth_token") or request.headers.get("X-Auth-Token", "")
        username = self.auth.verify_session(token)
        if not username or self.auth.users[username]["role"] != "admin":
            return web.json_response({"error": "Admin access required"}, status=403)

        target_user = request.match_info.get("username")
        if not self.auth.delete_user(target_user):
            return web.json_response({"error": "Cannot delete user"}, status=400)

        return web.json_response({"success": True})


# ============ 网关 Key API ============

class GatewayKeyAPI:
    """网关 Key 管理 API"""

    def __init__(self, key_manager: GatewayKeyManager, auth_manager: AuthManager):
        self.keys = key_manager
        self.auth = auth_manager

    def _check_admin(self, request) -> Optional[str]:
        """检查管理员权限"""
        token = request.cookies.get("auth_token") or request.headers.get("X-Auth-Token", "")
        username = self.auth.verify_session(token)
        if not username or self.auth.users[username]["role"] != "admin":
            return None
        return username

    async def get_keys(self, request: web.Request) -> web.Response:
        """获取 Key 列表"""
        if not self._check_admin(request):
            return web.json_response({"error": "Admin access required"}, status=403)
        return web.json_response({
            "keys": self.keys.list_keys(),
            "settings": self.keys.get_settings()
        })

    async def add_key(self, request: web.Request) -> web.Response:
        """添加新 Key"""
        if not self._check_admin(request):
            return web.json_response({"error": "Admin access required"}, status=403)

        try:
            body = await request.json()
        except Exception:
            body = {}

        name = body.get("name", "New Key")
        key_obj = self.keys.add_key(name)
        return web.json_response({"success": True, "key": key_obj})

    async def delete_key(self, request: web.Request) -> web.Response:
        """删除 Key"""
        if not self._check_admin(request):
            return web.json_response({"error": "Admin access required"}, status=403)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        key = body.get("key", "")
        if not self.keys.delete_key(key):
            return web.json_response({"error": "Key not found"}, status=404)
        return web.json_response({"success": True})

    async def update_settings(self, request: web.Request) -> web.Response:
        """更新设置"""
        if not self._check_admin(request):
            return web.json_response({"error": "Admin access required"}, status=403)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        self.keys.update_settings(
            require_key=body.get("require_key"),
            allow_any_key=body.get("allow_any_key")
        )
        return web.json_response({"success": True, "settings": self.keys.get_settings()})


# ============ CORS 中间件 ============

@web.middleware
async def cors_middleware(request, handler):
    """CORS 中间件 - 确保所有响应都包含 CORS 头"""
    # 处理 OPTIONS 预检请求
    if request.method == 'OPTIONS':
        response = web.Response(status=200)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, X-Auth-Token'
        response.headers['Access-Control-Max-Age'] = '86400'
        return response

    # 处理实际请求
    try:
        response = await handler(request)
    except web.HTTPException as e:
        response = e
    except Exception as e:
        # 捕获所有其他异常，返回带 CORS 头的错误响应
        response = web.json_response(
            {"error": {"message": str(e), "type": "server_error"}},
            status=500
        )

    # 添加 CORS 头到所有响应
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, X-Auth-Token'
    return response


# ============ 认证中间件 ============

def create_auth_middleware(auth_manager: AuthManager, key_manager: GatewayKeyManager):
    """创建认证中间件"""
    @web.middleware
    async def auth_middleware(request, handler):
        """API 认证中间件"""
        path = request.path

        # 公开路由（不需要认证）
        public_paths = [
            '/api/auth/login',
            '/api/auth/check',
            '/login',
            '/static/',
            '/favicon.ico'
        ]

        # 检查是否是公开路由
        for public in public_paths:
            if path.startswith(public) or path == public:
                return await handler(request)

        # OpenAI 兼容接口 - 检查 Bearer token
        if path.startswith('/v1/'):
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                api_key = auth_header[7:]  # 去掉 "Bearer " 前缀
                if key_manager.verify_key(api_key):
                    return await handler(request)
                return web.json_response(
                    {"error": {"message": "Invalid API key", "type": "invalid_api_key"}},
                    status=401
                )
            return web.json_response(
                {"error": {"message": "Missing Authorization header", "type": "invalid_request_error"}},
                status=401
            )

        # 管理页面和 API - 检查会话
        if path == '/' or path.startswith('/api/admin'):
            token = request.cookies.get("auth_token") or request.headers.get("X-Auth-Token", "")
            username = auth_manager.verify_session(token)

            if not username:
                # API 请求返回 401
                if path.startswith('/api/'):
                    return web.json_response({"error": "Not authenticated"}, status=401)
                # 页面请求重定向到登录页
                raise web.HTTPFound('/login')

            # 将用户信息存入 request
            request['user'] = username

        return await handler(request)

    return auth_middleware


# ============ 创建应用 ============

def create_app(pool_file: str = "account_pool.json") -> web.Application:
    """创建 aiohttp 应用"""
    pool = AccountPool(pool_file)
    pool.load()

    gateway = APIGateway(pool)
    web_api = WebAPI(pool, gateway)

    # 初始化认证管理器和网关 Key 管理器
    auth_manager = AuthManager()
    key_manager = GatewayKeyManager()
    auth_api = AuthAPI(auth_manager)
    key_api = GatewayKeyAPI(key_manager, auth_manager)

    # 创建带认证中间件的应用
    auth_middleware = create_auth_middleware(auth_manager, key_manager)
    app = web.Application(middlewares=[cors_middleware, auth_middleware])
    app['pool'] = pool
    app['gateway'] = gateway
    app['auth'] = auth_manager
    app['keys'] = key_manager

    # --- OPTIONS 处理 (CORS preflight) ---
    async def handle_options(request):
        return web.Response()

    # --- OpenAI 兼容 API 路由 ---
    app.router.add_route('OPTIONS', '/v1/chat/completions', handle_options)
    app.router.add_post('/v1/chat/completions', gateway.handle_chat_completions)
    app.router.add_route('OPTIONS', '/v1/models', handle_options)
    app.router.add_get('/v1/models', gateway.handle_models)

    # --- 认证 API 路由 ---
    app.router.add_post('/api/auth/login', auth_api.login)
    app.router.add_post('/api/auth/logout', auth_api.logout)
    app.router.add_get('/api/auth/check', auth_api.check_auth)
    app.router.add_post('/api/auth/password', auth_api.change_password)
    app.router.add_get('/api/auth/users', auth_api.list_users)
    app.router.add_post('/api/auth/users', auth_api.add_user)
    app.router.add_delete('/api/auth/users/{username}', auth_api.delete_user)

    # --- 网关 Key API 路由 ---
    app.router.add_get('/api/admin/keys', key_api.get_keys)
    app.router.add_post('/api/admin/keys', key_api.add_key)
    app.router.add_delete('/api/admin/keys', key_api.delete_key)
    app.router.add_post('/api/admin/keys/settings', key_api.update_settings)

    # --- 管理 API 路由 ---
    app.router.add_get('/api/admin/dashboard', web_api.get_dashboard)
    app.router.add_get('/api/admin/accounts', web_api.get_accounts)
    app.router.add_get('/api/admin/accounts/{email}', web_api.get_account_detail)
    app.router.add_post('/api/admin/accounts', web_api.add_account)
    app.router.add_delete('/api/admin/accounts/{email}', web_api.delete_account)
    app.router.add_post('/api/admin/accounts/{email}/toggle', web_api.toggle_account)
    app.router.add_post('/api/admin/accounts/{email}/health', web_api.health_check_account)
    app.router.add_post('/api/admin/health-check', web_api.health_check_all)
    app.router.add_post('/api/admin/import', web_api.import_accounts)
    app.router.add_get('/api/admin/logs', web_api.get_request_logs)
    app.router.add_post('/api/admin/register', web_api.batch_register)

    # --- 静态文件和 Web UI ---
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    if os.path.exists(static_dir):
        app.router.add_static('/static', static_dir)

    # 登录页面
    async def login_page(request):
        login_file = os.path.join(static_dir, 'login.html')
        if os.path.exists(login_file):
            return web.FileResponse(login_file)
        return web.Response(text="Login page not found", status=404)

    app.router.add_get('/login', login_page)

    # 首页路由（需要认证）
    async def index(request):
        index_file = os.path.join(static_dir, 'index.html')
        if os.path.exists(index_file):
            return web.FileResponse(index_file)
        return web.Response(text="APIPod Gateway - Web UI not found", status=404)

    app.router.add_get('/', index)

    return app


# ============ 入口 ============

def main():
    import argparse
    parser = argparse.ArgumentParser(description='APIPod Gateway Server')
    parser.add_argument('--host', default='0.0.0.0', help='绑定地址 (默认: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=None, help='端口 (默认: 9000)')
    parser.add_argument('--pool-file', default='account_pool.json', help='账号池文件路径')
    args = parser.parse_args()

    # 优先使用命令行参数，其次环境变量 PORT（Render 等平台使用），最后默认 9000
    port = args.port or int(os.environ.get('PORT', '9000'))

    app = create_app(args.pool_file)

    print(f"\n{'='*60}")
    print(f"APIPod Gateway Server")
    print(f"{'='*60}")
    print(f"Web UI:     http://localhost:{port}/")
    print(f"API Gateway: http://localhost:{port}/v1/chat/completions")
    print(f"Models:      http://localhost:{port}/v1/models")
    print(f"Admin API:   http://localhost:{port}/api/admin/dashboard")
    print(f"{'='*60}\n")

    web.run_app(app, host=args.host, port=port)


if __name__ == "__main__":
    main()
