#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试网关 API"""

import requests
import json

# 测试聊天接口
url = "http://localhost:9000/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer test-key"
}
data = {
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Say hello in 3 words"}]
}

print("Testing Gateway API...")
print(f"URL: {url}")
print()

try:
    response = requests.post(url, headers=headers, json=data, timeout=30)
    print(f"Status: {response.status_code}")
    print()

    result = response.json()
    if "choices" in result:
        content = result["choices"][0]["message"]["content"]
        print(f"Response: {content}")
    else:
        print(f"Response: {json.dumps(result, indent=2)}")

except Exception as e:
    print(f"Error: {e}")
