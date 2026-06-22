import json
import urllib.request
import urllib.error
import base64
import os

# ========== 配置区 ==========
# 优先从环境变量读取，也可直接替换为你的真实API Key
API_KEY = os.environ.get("ARK_API_KEY", "ark-fc4685b1-f775-4bb4-9c7a-7d8670569338-a63a9")
MODEL_NAME = "doubao-seed-2-0-pro-260215"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
# 测试图片路径（测试带图联网时需要，替换为本地真实图片路径）
TEST_IMAGE_PATH = "/tmp/test.jpg"
# ============================

def call_ark_api(payload):
    """通用调用火山方舟Responses API"""
    request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=request_data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return True, json.loads(body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        return False, f"HTTP错误 {e.code}: {error_body}"
    except Exception as e:
        return False, f"请求异常: {str(e)}"

def extract_answer(data):
    """从返回结果中提取纯文本回答"""
    if not isinstance(data, dict):
        return str(data)
    
    # 匹配非推理模式 output 结构
    if "output" in data:
        output = data["output"]
        if isinstance(output, str):
            return output.strip()
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict) and item.get("type") == "output_text":
                    return str(item.get("text", "")).strip()
    
    # 匹配推理模式 summary 结构
    if "summary" in data and isinstance(data["summary"], list):
        for item in data["summary"]:
            if isinstance(item, dict) and item.get("type") == "summary_text":
                return str(item.get("text", "")).strip()
    
    # 兜底返回完整原始结构
    return json.dumps(data, ensure_ascii=False, indent=2)

def test_text_web_search():
    """测试1：纯文本 + 联网搜索"""
    print("=" * 60)
    print("【测试1】纯文本 + 联网搜索")
    print("测试问题：今天的日期和佛山的天气是怎样的？")
    print("-" * 60)

    payload = {
        "model": MODEL_NAME,
        "thinking": {"type": "disabled"},
        "tools": [{"type": "web_search", "max_keyword": 3, "sources": ["douyin", "moji", "toutiao"]}],
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "今天的日期和佛山的天气是怎样的？请简洁回答。"
                    }
                ]
            }
        ]
    }

    success, result = call_ark_api(payload)
    if success:
        answer = extract_answer(result)
        print(f"✅ 请求成功")
        print(f"回答内容：{answer}")
        # 检测是否真实调用了联网工具
        raw_str = json.dumps(result, ensure_ascii=False)
        if "web_search" in raw_str or "搜索" in answer:
            print("ℹ️  检测到联网搜索调用痕迹")
        else:
            print("ℹ️  未检测到联网调用，可能使用内置知识回答")
    else:
        print(f"❌ 请求失败: {result}")
    print()

def test_vision_web_search():
    """测试2：多模态图像 + 联网搜索"""
    print("=" * 60)
    print("【测试2】多模态图像 + 联网搜索")
    print(f"测试图片：{TEST_IMAGE_PATH}")
    print("测试问题：识别图中物品，并查询该物品的市场价")
    print("-" * 60)

    if not os.path.exists(TEST_IMAGE_PATH):
        print(f"❌ 测试图片不存在，已跳过本测试。请修改 TEST_IMAGE_PATH 为真实图片路径")
        print()
        return

    # 图片转base64
    try:
        with open(TEST_IMAGE_PATH, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        print(f"❌ 图片读取失败: {e}")
        print()
        return

    payload = {
        "model": MODEL_NAME,
        "thinking": {"type": "disabled"},
        "tools": [{"type": "web_search"}],
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": f"data:image/jpeg;base64,{img_base64}"},
                    {"type": "input_text", "text": "识别图中的物品，并查询该物品的市场价，简洁回答。"}
                ]
            }
        ]
    }

    success, result = call_ark_api(payload)
    if success:
        answer = extract_answer(result)
        print(f"✅ 请求成功")
        print(f"回答内容：{answer}")
    else:
        print(f"❌ 请求失败: {result}")
    print()

if __name__ == "__main__":
    print(f"测试模型：{MODEL_NAME}")
    print(f"接口地址：{API_URL}")
    print()

    # 依次执行两项测试
    test_text_web_search()
    test_vision_web_search()

    print("=" * 60)
    print("全部测试完成")

    