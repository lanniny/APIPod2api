# APIPod Gateway

OpenAI 兼容的 API 网关服务，提供账号池管理、负载均衡和 Web UI 管理界面。

## 功能

- OpenAI 兼容 API（`/v1/chat/completions`, `/v1/models`）
- 账号池轮询和负载均衡
- Web UI 管理界面（账号管理、健康检查、请求日志）
- 用户认证和 API Key 管理

## 本地运行

```bash
pip install -r requirements-gateway.txt
python gateway_server.py
```

访问 `http://localhost:9000/login`，默认账号：`admin` / `admin123`

## Docker 运行

```bash
docker build -t apipod-gateway .
docker run -p 9000:9000 apipod-gateway
```

## 部署到 Render

### 方式一：通过 GitHub 自动部署

1. 将代码推送到 GitHub 仓库
2. 在 [render.com](https://render.com) 创建 Web Service，连接 GitHub 仓库
3. 选择 Docker 部署方式
4. 在 Render Dashboard 获取 Deploy Hook URL
5. 在 GitHub 仓库的 Settings > Secrets > Actions 中添加 `RENDER_DEPLOY_HOOK`
6. 后续推送到 `main` 分支将自动触发部署

### 方式二：通过 render.yaml (Blueprint)

1. 在 Render Dashboard 选择 "New Blueprint Instance"
2. 连接包含 `render.yaml` 的 GitHub 仓库
3. Render 会自动根据 `render.yaml` 配置创建服务

### 部署后操作

- 访问 Render 分配的公网 URL（如 `https://apipod-gateway.onrender.com`）
- 登录后通过 Web UI 导入账号数据
- （可选）在 Cloudflare DNS 绑定自定义域名

## 备选方案：Cloudflare Tunnel

无需修改代码，本机运行后通过隧道暴露到公网：

```bash
# 安装 cloudflared
winget install Cloudflare.cloudflared

# 启动网关
python gateway_server.py

# 另一个终端，创建隧道
cloudflared tunnel --url http://localhost:9000
```

会获得一个临时公网 URL（如 `https://xxx-xxx.trycloudflare.com`）。需要本机保持在线。

## API 使用

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://your-gateway-url/v1",
    api_key="sk-any-key"
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello"}]
)
print(response.choices[0].message.content)
```

## 项目结构

```
├── gateway_server.py       # 网关主服务
├── pool_manager.py         # 账号池管理器
├── static/                 # Web UI 前端文件
│   ├── index.html          # 管理界面
│   └── login.html          # 登录页面
├── Dockerfile              # Docker 构建配置
├── render.yaml             # Render 部署配置
├── requirements-gateway.txt # 网关依赖（轻量）
├── requirements.txt        # 完整依赖（含注册脚本）
├── register.py             # 单个账号注册脚本
├── batch_register.py       # 批量注册脚本
└── .github/workflows/
    └── deploy.yml          # GitHub Actions 自动部署
```
