#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APIPod 自动注册脚本
自动注册账号并创建 API Key
"""

import asyncio
import random
import string
import sys
import io
from playwright.async_api import async_playwright

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def generate_random_string(length=8):
    """生成随机字符串"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


async def register_apipod(email_suffix):
    """
    自动注册 APIPod 账号并创建 API Key

    Args:
        email_suffix: 邮箱后缀

    Returns:
        dict: 包含注册信息和 API Key
    """
    random_str = generate_random_string()
    username = random_str
    email = f"{random_str}@{email_suffix}"
    password = f"Pass{random_str}!123"

    result = {
        "username": username,
        "email": email,
        "password": password,
        "api_key": None,
        "base_url": "https://api.apipod.ai/v1",
        "success": False
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            # 1. 访问首页
            print(f"[1] 访问 APIPod 首页...")
            await page.goto("https://www.apipod.ai/")
            await page.wait_for_load_state("networkidle")

            # 2. 点击注册按钮
            print(f"[2] 点击注册按钮...")
            await page.click('button:text("Start for free")')
            await asyncio.sleep(2)

            # 3. 填写注册表单
            print(f"[3] 填写注册信息...")
            print(f"    用户名: {username}")
            print(f"    邮箱: {email}")

            # 等待输入框出现
            await page.wait_for_selector('input[placeholder="Your username"]', timeout=10000)
            await page.fill('input[placeholder="Your username"]', username)
            await page.fill('input[placeholder="name@example.com"]', email)
            await page.fill('input[placeholder="••••••••"]', password)

            # 4. 提交注册
            print(f"[4] 提交注册...")
            await page.click('button:text("Create account")')

            # 等待注册成功（会自动跳转到控制台）
            await page.wait_for_url("**/console**", timeout=20000)
            print(f"[✓] 注册成功，已自动登录")

            # 5. 进入 API Keys 页面
            print(f"[5] 进入 API Keys 页面...")
            await page.goto("https://www.apipod.ai/console/api-keys")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)

            # 6. 创建 API Key
            print(f"[6] 创建 API Key...")
            await page.click('button:text("Create key")')
            await asyncio.sleep(1.5)

            # 点击对话框内的确认创建按钮（使用更精确的选择器）
            dialog = page.locator('div[role="dialog"]')
            create_btn = dialog.locator('button:text("Create Key")')
            await create_btn.click(force=True)
            await asyncio.sleep(2)

            # 7. 提取 API Key
            print(f"[7] 提取 API Key...")
            # 等待成功对话框出现
            await page.wait_for_selector('text=API Key Created Successfully', timeout=10000)

            # API Key 在 Authorization header 示例中
            key_element = await page.query_selector('code:has-text("Authorization: Bearer")')
            if key_element:
                auth_text = await key_element.inner_text()
                # 格式: Authorization: Bearer sk-xxx
                api_key = auth_text.replace("Authorization: Bearer ", "").strip()
                result["api_key"] = api_key
                result["success"] = True
                print(f"[✓] API Key 创建成功")

            # 关闭对话框
            close_btn = page.locator('button:text("I have saved it")')
            await close_btn.click(force=True)

        except Exception as e:
            print(f"[✗] 错误: {e}")
            result["error"] = str(e)

        finally:
            await browser.close()

    return result


def print_result(result):
    """打印注册结果"""
    print("\n" + "=" * 50)
    print("APIPod 注册结果")
    print("=" * 50)

    if result["success"]:
        print(f"状态: ✓ 成功")
        print(f"\n账号信息:")
        print(f"  用户名: {result['username']}")
        print(f"  邮箱:   {result['email']}")
        print(f"  密码:   {result['password']}")
        print(f"\nAPI 信息:")
        print(f"  Base URL: {result['base_url']}")
        print(f"  API Key:  {result['api_key']}")
    else:
        print(f"状态: ✗ 失败")
        if "error" in result:
            print(f"错误: {result['error']}")

    print("=" * 50)


async def main():
    import argparse
    parser = argparse.ArgumentParser(description='APIPod 自动注册脚本')
    parser.add_argument('--suffix', '-s', required=True,
                        help='邮箱后缀')
    args = parser.parse_args()

    result = await register_apipod(email_suffix=args.suffix)
    print_result(result)
    return result


if __name__ == "__main__":
    asyncio.run(main())
