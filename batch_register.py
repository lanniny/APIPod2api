#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APIPod 批量注册脚本
持续注册账号并保存结果
"""

import asyncio
import json
from datetime import datetime
import sys
import random
import string
from playwright.async_api import async_playwright
from openai import OpenAI


def generate_random_string(length=8):
    """生成随机字符串"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


async def register_apipod_simple(email_suffix):
    """简化版注册函数"""
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
            print(f"[1] 访问 APIPod 首页...")
            await page.goto("https://www.apipod.ai/")
            await page.wait_for_load_state("networkidle")

            print(f"[2] 点击注册按钮...")
            await page.click('button:text("Start for free")')
            await asyncio.sleep(2)

            print(f"[3] 填写注册信息...")
            print(f"    用户名: {username}")
            print(f"    邮箱: {email}")

            await page.wait_for_selector('input[placeholder="Your username"]', timeout=10000)
            await page.fill('input[placeholder="Your username"]', username)
            await page.fill('input[placeholder="name@example.com"]', email)
            await page.fill('input[placeholder="••••••••"]', password)

            print(f"[4] 提交注册...")
            await page.click('button:text("Create account")')

            await page.wait_for_url("**/console**", timeout=20000)
            print(f"[OK] 注册成功，已自动登录")

            print(f"[5] 进入 API Keys 页面...")
            await page.goto("https://www.apipod.ai/console/api-keys")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)

            print(f"[6] 创建 API Key...")
            await page.click('button:text("Create key")')
            await asyncio.sleep(1.5)

            dialog = page.locator('div[role="dialog"]')
            create_btn = dialog.locator('button:text("Create Key")')
            await create_btn.click(force=True)
            await asyncio.sleep(2)

            print(f"[7] 提取 API Key...")
            await page.wait_for_selector('text=API Key Created Successfully', timeout=10000)

            key_element = await page.query_selector('code:has-text("Authorization: Bearer")')
            if key_element:
                auth_text = await key_element.inner_text()
                api_key = auth_text.replace("Authorization: Bearer ", "").strip()
                result["api_key"] = api_key
                result["success"] = True
                print(f"[OK] API Key 创建成功")

            close_btn = page.locator('button:text("I have saved it")')
            await close_btn.click(force=True)

        except Exception as e:
            print(f"[ERROR] 错误: {e}")
            result["error"] = str(e)

        finally:
            await browser.close()

    return result


def test_api_key_simple(api_key, base_url="https://api.apipod.ai/v1"):
    """简化版 API 测试"""
    try:
        print(f"[测试] 正在测试 API Key...")
        client = OpenAI(base_url=base_url, api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello, please respond with just 'OK'"}],
            max_tokens=10
        )
        result = response.choices[0].message.content
        print(f"[OK] API 测试成功: {result}")
        return True
    except Exception as e:
        print(f"[ERROR] API 测试失败: {e}")
        return False


async def batch_register(count, email_suffix, output_file="accounts.json", test_api=True):
    """批量注册账号"""
    results = []
    success_count = 0
    fail_count = 0

    print(f"\n{'='*60}")
    print(f"开始批量注册 APIPod 账号")
    print(f"{'='*60}")
    print(f"目标数量: {count}")
    print(f"邮箱后缀: {email_suffix}")
    print(f"输出文件: {output_file}")
    print(f"API 测试: {'启用' if test_api else '禁用'}")
    print(f"{'='*60}\n")

    for i in range(1, count + 1):
        print(f"\n[{i}/{count}] 开始注册第 {i} 个账号...")
        print("-" * 60)

        try:
            # 注册账号
            result = await register_apipod_simple(email_suffix)

            if result["success"]:
                success_count += 1

                # 测试 API Key
                if test_api and result["api_key"]:
                    print(f"\n[测试] 验证 API Key 可用性...")
                    api_valid = test_api_key_simple(result["api_key"])
                    result["api_tested"] = True
                    result["api_valid"] = api_valid
                else:
                    result["api_tested"] = False
                    result["api_valid"] = None

                # 添加时间戳
                result["created_at"] = datetime.now().isoformat()

                print(f"\n[OK] 第 {i} 个账号注册成功")
                print(f"    用户名: {result['username']}")
                print(f"    API Key: {result['api_key'][:30]}...")

            else:
                fail_count += 1
                print(f"\n[ERROR] 第 {i} 个账号注册失败")
                if "error" in result:
                    print(f"    错误: {result['error']}")

            results.append(result)

            # 实时保存结果
            save_results(results, output_file)

            # 显示进度
            print(f"\n[进度] 成功: {success_count} | 失败: {fail_count} | 总计: {i}/{count}")

            # 间隔等待（避免请求过快）
            if i < count:
                wait_time = 3
                print(f"\n[等待] {wait_time} 秒后继续...")
                await asyncio.sleep(wait_time)

        except KeyboardInterrupt:
            print(f"\n\n[中断] 用户取消操作")
            break
        except Exception as e:
            fail_count += 1
            print(f"\n[ERROR] 第 {i} 个账号注册异常: {e}")
            results.append({
                "success": False,
                "error": str(e),
                "created_at": datetime.now().isoformat()
            })

    # 最终统计
    print(f"\n\n{'='*60}")
    print(f"批量注册完成")
    print(f"{'='*60}")
    print(f"总计: {len(results)} 个")
    print(f"成功: {success_count} 个")
    print(f"失败: {fail_count} 个")
    if len(results) > 0:
        print(f"成功率: {success_count/len(results)*100:.1f}%")
    print(f"结果已保存到: {output_file}")
    print(f"{'='*60}\n")

    return results


def save_results(results, output_file):
    """保存结果到 JSON 文件"""
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[警告] 保存结果失败: {e}")


def load_results(output_file):
    """加载已有结果"""
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[警告] 加载结果失败: {e}")
        return []


async def main():
    import argparse
    parser = argparse.ArgumentParser(description='APIPod 批量注册脚本')
    parser.add_argument('--count', '-c', type=int, default=5,
                        help='注册数量（默认: 5）')
    parser.add_argument('--suffix', '-s', required=True,
                        help='邮箱后缀')
    parser.add_argument('--output', '-o', default='accounts.json',
                        help='输出文件路径（默认: accounts.json）')
    parser.add_argument('--no-test', action='store_true',
                        help='不测试 API Key')
    args = parser.parse_args()

    await batch_register(
        count=args.count,
        email_suffix=args.suffix,
        output_file=args.output,
        test_api=not args.no_test
    )


if __name__ == "__main__":
    asyncio.run(main())
