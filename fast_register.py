#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APIPod 高速并行注册脚本
支持多线程并行注册，最大化注册速度
"""

import asyncio
import json
from datetime import datetime
import sys
import random
import string
from playwright.async_api import async_playwright
import argparse
import os

# 输出文件锁
import threading
file_lock = threading.Lock()


def generate_random_string(length=8):
    """生成随机字符串"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


async def register_single(email_suffix, worker_id):
    """单个注册任务（优化速度版）"""
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
        "success": False,
        "created_at": datetime.now().isoformat()
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # 访问首页
            await page.goto("https://www.apipod.ai/", wait_until="domcontentloaded")

            # 点击注册
            await page.click('button:text("Start for free")')
            await asyncio.sleep(1)

            # 填写表单
            await page.wait_for_selector('input[placeholder="Your username"]', timeout=8000)
            await page.fill('input[placeholder="Your username"]', username)
            await page.fill('input[placeholder="name@example.com"]', email)
            await page.fill('input[placeholder="••••••••"]', password)

            # 提交
            await page.click('button:text("Create account")')
            await page.wait_for_url("**/console**", timeout=15000)

            # 进入 API Keys 页面
            await page.goto("https://www.apipod.ai/console/api-keys", wait_until="domcontentloaded")
            await asyncio.sleep(0.5)

            # 创建 Key
            await page.click('button:text("Create key")')
            await asyncio.sleep(1)

            dialog = page.locator('div[role="dialog"]')
            create_btn = dialog.locator('button:text("Create Key")')
            await create_btn.click(force=True)
            await asyncio.sleep(1.5)

            # 提取 Key
            await page.wait_for_selector('text=API Key Created Successfully', timeout=8000)
            key_element = await page.query_selector('code:has-text("Authorization: Bearer")')
            if key_element:
                auth_text = await key_element.inner_text()
                api_key = auth_text.replace("Authorization: Bearer ", "").strip()
                result["api_key"] = api_key
                result["success"] = True

            close_btn = page.locator('button:text("I have saved it")')
            await close_btn.click(force=True)

        except Exception as e:
            result["error"] = str(e)

        finally:
            await browser.close()

    return result


def save_result(result, output_file):
    """线程安全保存结果"""
    with file_lock:
        # 读取现有数据
        if os.path.exists(output_file):
            with open(output_file, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                except:
                    data = []
        else:
            data = []

        # 只保存成功的
        if result["success"]:
            data.append(result)
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)


async def worker(worker_id, email_suffix, output_file, task_queue, stats):
    """工作线程"""
    while True:
        try:
            task_num = task_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        try:
            result = await register_single(email_suffix, worker_id)

            if result["success"]:
                stats["success"] += 1
                save_result(result, output_file)
                print(f"[W{worker_id}] #{task_num} OK - {result['username']} - {result['api_key'][:25]}...")
            else:
                stats["fail"] += 1
                error_msg = result.get("error", "Unknown")[:50]
                print(f"[W{worker_id}] #{task_num} FAIL - {error_msg}")

        except Exception as e:
            stats["fail"] += 1
            print(f"[W{worker_id}] #{task_num} ERROR - {str(e)[:50]}")

        stats["done"] += 1

        # 显示进度
        total = stats["success"] + stats["fail"]
        if total % 5 == 0:
            print(f"\n>>> Progress: {stats['success']} success / {stats['fail']} fail / {stats['done']} done <<<\n")


async def batch_register_parallel(total_count, email_suffix, output_file, workers=3):
    """并行批量注册"""
    print(f"\n{'='*60}")
    print(f"APIPod Fast Parallel Registration")
    print(f"{'='*60}")
    print(f"Target: {total_count} accounts")
    print(f"Workers: {workers} parallel")
    print(f"Email suffix: {email_suffix}")
    print(f"Output: {output_file}")
    print(f"{'='*60}\n")

    # 创建任务队列
    task_queue = asyncio.Queue()
    for i in range(1, total_count + 1):
        await task_queue.put(i)

    # 统计
    stats = {"success": 0, "fail": 0, "done": 0}

    # 启动工作线程
    worker_tasks = []
    for i in range(workers):
        task = asyncio.create_task(worker(i + 1, email_suffix, output_file, task_queue, stats))
        worker_tasks.append(task)

    # 等待所有完成
    await asyncio.gather(*worker_tasks)

    # 最终统计
    print(f"\n{'='*60}")
    print(f"Registration Complete")
    print(f"{'='*60}")
    print(f"Total: {stats['done']}")
    print(f"Success: {stats['success']}")
    print(f"Failed: {stats['fail']}")
    print(f"Success Rate: {stats['success']/max(stats['done'],1)*100:.1f}%")
    print(f"{'='*60}\n")

    return stats


def main():
    parser = argparse.ArgumentParser(description='APIPod Fast Registration')
    parser.add_argument('--count', type=int, default=10, help='Number of accounts')
    parser.add_argument('--suffix', default='tmpmail.net', help='Email suffix')
    parser.add_argument('--output', default='accounts.json', help='Output file')
    parser.add_argument('--workers', type=int, default=3, help='Parallel workers')
    args = parser.parse_args()

    asyncio.run(batch_register_parallel(
        args.count,
        args.suffix,
        args.output,
        args.workers
    ))


if __name__ == "__main__":
    main()
