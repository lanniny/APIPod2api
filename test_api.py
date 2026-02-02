#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 APIPod API Key 可用性"""

import sys
import io
from openai import OpenAI

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def test_api_key(api_key, base_url="https://api.apipod.ai/v1"):
    """测试 API Key 是否可用"""
    try:
        print(f"[测试] 正在测试 API Key: {api_key[:20]}...")

        client = OpenAI(
            base_url=base_url,
            api_key=api_key
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello, please respond with just 'OK'"}],
            max_tokens=10
        )

        result = response.choices[0].message.content
        print(f"[✓] API 测试成功")
        print(f"[响应] {result}")
        return True

    except Exception as e:
        print(f"[✗] API 测试失败: {e}")
        return False

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        api_key = sys.argv[1]
    else:
        api_key = "sk-585341c8052ab7fbb6fa3bb4fa6e78200b96cc3d75f0e69fcaab9b89720ec9e5"

    test_api_key(api_key)
