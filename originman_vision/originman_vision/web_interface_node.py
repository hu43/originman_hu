#!/usr/bin/env python3
# encoding:utf-8
from flask import Flask, request, render_template_string, jsonify
from flask_socketio import SocketIO
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter
from rcl_interfaces.srv import SetParameters
from std_msgs.msg import String, Empty
import threading
import json
import os
import sys
import random
from openai import OpenAI

# --- Configuration ---
DASHSCOPE_TEXT_MODEL = os.environ.get("DASHSCOPE_TEXT_MODEL", "qwen-plus")
DASHSCOPE_API_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


ACTION_CONFIRMATIONS = [
    "好的，看我的！",
    "没问题，瞧好了！",
    "收到，这就给您安排上！",
    "小菜一碟。",
    "好的，请稍等片刻。",
    "明白，我这就执行！",
    "了解，小事一桩！"
]

# --- Global Variables ---
current_dashscope_api_key = None
openai_client = None
app = Flask(__name__)
socketio = SocketIO(app)
ros_node = None
ros_publisher_action = None
ros_publisher_vision = None
ros_publisher_tts_input = None
ros_publisher_cancel_singing = None
ros_publisher_voice_control = None
ros_speech_state_subscriber = None
param_client_tts = None
param_client_vision = None
param_client_voice = None
last_speech_state = None
speech_state_lock = threading.Lock()
speech_tts_completion_event = threading.Event()


# --- OriginMan Robot Action Definitions ---
ORIGINMAN_BASE_ACTIONS = ["stand", "go_forward", "back_fast", "left_move_fast", "right_move_fast", "push_ups", "sit_ups", "turn_left", "turn_right", "wave", "bow", "squat", "chest", "left_shot_fast", "right_shot_fast", "wing_chun", "left_uppercut", "right_uppercut", "left_kick", "right_kick", "stand_up_front", "stand_up_back", "twist", "stepping", "jugong", "weightlifting"]
ORIGINMAN_DANCE_ACTIONS_NUMERIC_STR = [str(i) for i in range(16, 25)]
ORIGINMAN_SONG_IDS_STR = [str(i) for i in range(16, 25)]
ORIGINMAN_ACTIONS = ORIGINMAN_BASE_ACTIONS + ORIGINMAN_DANCE_ACTIONS_NUMERIC_STR
ORIGINMAN_ACTIONS_CHINESE_MAP = {"stand": "立正", "go_forward": "前进", "back_fast": "后退", "left_move_fast": "左移", "right_move_fast": "右移", "push_ups": "俯卧撑", "sit_ups": "仰卧起坐", "turn_left": "左转", "turn_right": "右转", "wave": "挥手", "bow": "鞠躬", "squat": "下蹲", "chest": "庆祝", "left_shot_fast": "左脚踢", "right_shot_fast": "右脚踢", "wing_chun": "咏春", "left_uppercut": "左勾拳", "right_uppercut": "右勾拳", "left_kick": "左侧踢", "right_kick": "右侧踢", "stand_up_front": "前跌倒起立", "stand_up_back": "后跌倒起立", "twist": "扭腰", "stepping": "原地踏步", "jugong": "鞠躬", "weightlifting": "举重"}
for dance_num_str in ORIGINMAN_DANCE_ACTIONS_NUMERIC_STR:
    ORIGINMAN_ACTIONS_CHINESE_MAP[dance_num_str] = f"舞蹈动作{dance_num_str}"
action_descriptions_for_prompt = "\n".join([f"  - {en_action} (中文名: {ORIGINMAN_ACTIONS_CHINESE_MAP.get(en_action, en_action)})" for en_action in ORIGINMAN_ACTIONS])
song_ids_for_prompt = ", ".join(ORIGINMAN_SONG_IDS_STR)


# --- ROS Related Functions ---
def web_display_callback(msg):
    global socketio
    text_to_display = msg.data
    socketio.emit('new_message', {'text': text_to_display, 'type': 'bot-message'})
    if ros_node:
        ros_node.get_logger().info(f"Pushed to web UI via WebSocket: '{text_to_display}'")

def init_ros():
    global ros_node, ros_publisher_action, ros_publisher_vision, ros_publisher_tts_input, current_dashscope_api_key, ros_speech_state_subscriber, ros_publisher_cancel_singing, ros_publisher_voice_control, param_client_tts, param_client_vision, param_client_voice
    ros_node = rclpy.create_node('web_interface_node')
    current_dashscope_api_key = os.environ.get("DASHSCOPE_API_KEY")
    if current_dashscope_api_key:
        ros_node.get_logger().info("DASHSCOPE_API_KEY 从环境变量加载为初始值。")
        initialize_openai_client()
    else:
        ros_node.get_logger().warn("未在环境变量中找到 DASHSCOPE_API_KEY。请通过Web界面进行设置。")
    ros_publisher_action = ros_node.create_publisher(String, '/robot_action_command', 10)
    ros_publisher_vision = ros_node.create_publisher(String, '/vision_question', 10)
    ros_publisher_tts_input = ros_node.create_publisher(String, '/tts_input', 10)
    ros_publisher_cancel_singing = ros_node.create_publisher(Empty, '/robot_cancel_singing_request', 10)
    ros_publisher_voice_control = ros_node.create_publisher(String, '/voice_control_command', 10)
    ros_speech_state_subscriber = ros_node.create_subscription(String, '/speech_state', speech_state_callback, 10)
    recognized_text_subscriber = ros_node.create_subscription(String, '/recognized_text', lambda msg: process_recognized_text(ros_node, msg, socketio), 10)
    web_display_subscriber = ros_node.create_subscription(String, '/web_display_text', web_display_callback, 10)
    ros_node.get_logger().info('Web接口ROS节点相关组件已初始化。')
    ros_node.get_logger().info('正在创建参数服务客户端以分发API Key...')
    param_client_tts = ros_node.create_client(SetParameters, '/text_to_speech_node/set_parameters')
    param_client_vision = ros_node.create_client(SetParameters, '/image_caption_node/set_parameters')
    param_client_voice = ros_node.create_client(SetParameters, '/voice_control_node/set_parameters')
    threading.Thread(target=wait_for_param_services, daemon=True).start()

def speech_state_callback(msg):
    global last_speech_state, speech_tts_completion_event, ros_node
    with speech_state_lock:
        last_speech_state = msg.data
    if ros_node:
        ros_node.get_logger().debug(f"收到语音状态: {msg.data}")
    if msg.data == "正在聆听":
        speech_tts_completion_event.set()

def initialize_openai_client():
    global openai_client, current_dashscope_api_key, ros_node
    log_source = ros_node.get_logger() if ros_node else print
    if current_dashscope_api_key:
        try:
            openai_client = OpenAI(api_key=current_dashscope_api_key, base_url=DASHSCOPE_API_BASE_URL)
            log_source.info("Web UI's internal OpenAI client for Dashscope 已成功初始化。")
        except Exception as e:
            log_source.error(f"初始化 Web UI's internal OpenAI client 失败: {e}")
            openai_client = None
    else:
        log_source.warn("Web UI: Dashscope API Key 未提供，内部 OpenAI client 未初始化。")
        openai_client = None

def wait_for_param_services():
    clients = {"TTS": param_client_tts, "Vision": param_client_vision, "Voice": param_client_voice}
    for name, client in clients.items():
        if not client.wait_for_service(timeout_sec=5.0):
            ros_node.get_logger().error(f'无法连接到 {name} 节点的参数服务！该节点将无法接收API Key。')
        else:
            ros_node.get_logger().info(f'已成功连接到 {name} 节点的参数服务。')

def call_intent_parsing_llm(user_query):
    global ros_node, openai_client
    log_source = ros_node.get_logger() if ros_node else print
    log_source.info(f"向Dashscope文本LLM ({DASHSCOPE_TEXT_MODEL}) 发送查询: '{user_query}'")
    if not openai_client:
        log_source.error("Dashscope OpenAI 客户端未初始化！ (API Key可能未配置)")
        return [{"type": "error", "message": "服务端错误：API Key未配置或无效"}]
    system_prompt = f"""你是一个基于AI大模型的机器人助手，帮助用户控制名为OriginMan的机器人。
分析用户的指令，并将其转换为结构化的JSON命令。
机器人有以下主要能力：
1. "query_vision": 提出关于机器人所见内容的问题。结果应包含 "prompt_for_vision" 字段，内容为用户原始的视觉问题，识别的结果可以稍微简洁。
2. "perform_action": 执行一个物理动作。结果应包含 "action_name" 字段。
   对于像 "前进", "后退" 这样的动作，如果用户指定了次数（例如“前进两步”，“后退3次”），你应该在JSON中包含一个 "repetitions" 字段，其值为数字。如果未指定次数，则 "repetitions" 默认为 1。
   机器人能够执行以下物理动作。在生成JSON时，"action_name"字段必须严格使用括号前的英文指令名 (例如 "go_forward", 或对于舞蹈动作使用如 "16", "17" 这样的数字字符串):
{action_descriptions_for_prompt}
   当你需要生成 "perform_action" 类型的JSON时，"action_name" 字段必须严格使用上述列表中的英文指令名。 "repetitions" 字段应为整数，并在所有动作结束后自动添加一个"stand": "立正"指令让机器人站好。
3. "sing_song": 让机器人唱歌。结果应包含 "song_id" 字段，其值为歌曲的编号字符串 (例如 "16", "17", ..., "24")。
   可用的歌曲编号有: {song_ids_for_prompt}。
   如果用户说“唱首歌”或“来一首歌”等没有指定具体歌曲的指令，你必须从可用的歌曲编号中随机选择一个。不要询问用户。
4. "cancel_singing": 当用户说“别唱了”、“停止唱歌”、“安静”等意图停止当前正在播放的歌曲时，使用此类型。此类型不需要额外参数。
5. "direct_response": 如果用户的指令是问候、简单聊天、询问机器人能力（例如“你能做什么动作？”）或无法归类为上述类别，你可以直接生成一个回答。结果应包含 "text_to_speak" 字段。

当你回答用户关于可执行动作的问题时 (例如用户问：“你会做什么？”或“有哪些动作？”)，你应该在 "text_to_speak" 字段中用中文列出这些动作的中文名，并选择性的列出来，不需要全部列出。例如：“我会的动作有立正、前进、后退、挥手、鞠躬、各种舞蹈动作、我还会唱歌呢，等等。”。你不需要明确向用户说明“舞蹈动作16”、“歌曲17”这些具体的编号，只需要和用户说你会不同的舞蹈动作和歌曲就好。
如果用户发出一个模糊的跳舞请求，比如“跳个舞”或“表演一个舞蹈”，甚至说“做一些炫酷的动作”等，而没有指明具体是哪一个，你必须从机器人可执行的舞蹈动作编号（即 "16" 到 "24"）中自行选择一个，并生成 "perform_action" 类型的JSON。例如，你可以选择 "17"或者"20"等等。不要询问用户。确保 action_name 是一个有效的数字字符串。

请总是输出一个JSON对象列表，每个对象代表一个步骤。
如果用户指令包含多个步骤（例如“你看到了什么然后鞠个躬再唱首歌然后停掉”），请为每个步骤生成一个JSON对象。
示例:
用户: "桌子上有什么？然后鞠个躬，再唱一首歌" ->
[
 {{"type": "query_vision", "prompt_for_vision": "桌子上有什么？"}},
 {{"type": "perform_action", "action_name": "bow", "repetitions": 1}},
 {{"type": "sing_song", "song_id": "18"}}
]
用户: "前进两步" -> [{{"type": "perform_action", "action_name": "go_forward", "repetitions": 2}}]
用户: "唱首歌" -> [{{"type": "sing_song", "song_id": "{random.choice(ORIGINMAN_SONG_IDS_STR)}"}}]
用户: "别唱了" -> [{{"type": "cancel_singing"}}]
用户: "你好" -> [{{"type": "direct_response", "text_to_speak": "你好！有什么可以帮您的吗？"}}]
用户: "你能做什么动作" -> [{{"type": "direct_response", "text_to_speak": "我可以做的动作包括：立正、前进、后退、挥手、鞠躬、各种舞蹈以及唱歌等等。"}}]

如果无法理解或指令无效，请返回 [{{"type": "error", "message": "无法理解的指令"}}].
确保你的输出严格遵守JSON格式，并且是一个列表。"""
    final_system_prompt = system_prompt.replace("{random.choice(ORIGINMAN_DANCE_ACTIONS_NUMERIC_STR)}", random.choice(ORIGINMAN_DANCE_ACTIONS_NUMERIC_STR))
    final_system_prompt = final_system_prompt.replace("{random.choice(ORIGINMAN_SONG_IDS_STR)}", random.choice(ORIGINMAN_SONG_IDS_STR))
    try:
        completion = openai_client.chat.completions.create(model=DASHSCOPE_TEXT_MODEL, messages=[{"role": "system", "content": final_system_prompt}, {"role": "user", "content": user_query}])
        content_text = completion.choices[0].message.content.strip()
        log_source.info(f"Dashscope LLM 原始回复内容: {content_text}")
        if content_text.startswith("```json"): content_text = content_text[len("```json"):].strip()
        if content_text.endswith("```"): content_text = content_text[:-len("```")].strip()
        try:
            parsed_commands = json.loads(content_text)
            if not isinstance(parsed_commands, list):
                log_source.warn(f"LLM未返回列表，而是: {type(parsed_commands)}. 将其包装在列表中。")
                return [parsed_commands]
            return parsed_commands
        except json.JSONDecodeError as e:
            log_source.error(f"LLM输出的JSON解析失败: {e}. 内容: {content_text}")
            return [{"type": "error", "message": f"LLM输出格式错误: {content_text}"}]
    except Exception as e:
        log_source.error(f"调用Dashscope LLM API时发生错误: {e}")
        return [{"type": "error", "message": f"LLM API请求错误: {str(e)}"}]


def _handle_sequential_execution_in_background(commands_for_execution):
    global ros_node, ros_publisher_tts_input, ros_publisher_action, ros_publisher_vision, speech_tts_completion_event
    if not ros_node:
        print("[后台线程错误] ros_node 未初始化！")
        return
    ros_node.get_logger().info(f"[后台线程] 开始执行任务序列: {commands_for_execution}")
    for cmd_detail in commands_for_execution:
        cmd_type = cmd_detail.get("type")
        data = cmd_detail.get("data")
        if cmd_type == "direct_response_for_tts":
            text_to_speak = data.get("text_to_speak")
            if text_to_speak and ros_publisher_tts_input:
                speech_tts_completion_event.clear()
                tts_msg = String()
                tts_msg.data = text_to_speak
                ros_publisher_tts_input.publish(tts_msg)
                ros_node.get_logger().info(f"[后台线程] TTS指令已发送: '{text_to_speak}', 等待播报完成...")
                if speech_tts_completion_event.wait(timeout=60.0):
                    ros_node.get_logger().info("[后台线程] TTS播报完成。")
                else:
                    ros_node.get_logger().warn("[后台线程] TTS播报等待超时。")
        elif cmd_type == "perform_action_later":
            action_name = data.get("action_name")
            repetitions = data.get("repetitions", 1)
            if action_name and action_name in ORIGINMAN_ACTIONS and ros_publisher_action:
                action_payload = {"action_name": action_name, "repetitions": repetitions}
                msg_str = json.dumps(action_payload)
                msg = String()
                msg.data = msg_str
                ros_publisher_action.publish(msg)
                ros_node.get_logger().info(f"[后台线程] 动作指令已发送: {msg_str}")
            else:
                ros_node.get_logger().warn(f"[后台线程] 无效动作 '{action_name}' 或发布器未就绪，跳过执行。")
        elif cmd_type == "sing_song_later":
            song_id = data.get("song_id")
            if song_id and ros_publisher_action:
                action_payload = {"action_name": "sing_song", "song_id": song_id}
                msg_str = json.dumps(action_payload)
                msg = String()
                msg.data = msg_str
                ros_publisher_action.publish(msg)
                ros_node.get_logger().info(f"[后台线程] 唱歌指令已发送: {msg_str}")
            else:
                ros_node.get_logger().warn(f"[后台线程] 无效歌曲ID '{song_id}' 或发布器未就绪，跳过演唱。")
        elif cmd_type == "query_vision_later":
            prompt = data.get("prompt_for_vision")
            if prompt and ros_publisher_vision:
                msg = String()
                msg.data = prompt
                ros_publisher_vision.publish(msg)
                ros_node.get_logger().info(f"[后台线程] 视觉问题已发送: {prompt}")
            else:
                ros_node.get_logger().warn(f"[后台线程] 视觉问题为空或发布器未就绪，跳过。")
    ros_node.get_logger().info("[后台线程] 所有后台任务执行完毕。")

def _process_and_execute_llm_commands(parsed_commands):
    global ros_node, ros_publisher_cancel_singing
    
    sequential_execution_plan_for_bg = []
    
    # This variable is now only used for direct HTTP responses (e.g., errors)
    primary_text_for_web_display = None
    is_error = False

    if not parsed_commands or not isinstance(parsed_commands, list):
        is_error = True
        primary_text_for_web_display = "抱歉，无法解析指令。"
    elif len(parsed_commands) == 1 and parsed_commands[0].get("type") == "error":
        is_error = True
        primary_text_for_web_display = parsed_commands[0].get("message", "LLM返回未知错误")
    else:
        # Check if the sequence contains an action, to avoid multiple confirmations
        contains_action = any(cmd.get("type") == "perform_action" for cmd in parsed_commands)
        confirmation_sent = False

        for cmd in parsed_commands:
            cmd_type = cmd.get("type")
            
            if cmd_type == "direct_response":
                text_to_speak = cmd.get("text_to_speak")
                if text_to_speak:
                    sequential_execution_plan_for_bg.append({"type": "direct_response_for_tts", "data": {"text_to_speak": text_to_speak}})
            
            elif cmd_type == "perform_action":
                # If this is the first action in a sequence, send a confirmation first.
                if contains_action and not confirmation_sent:
                    confirmation_text = random.choice(ACTION_CONFIRMATIONS)
                    sequential_execution_plan_for_bg.append({"type": "direct_response_for_tts", "data": {"text_to_speak": confirmation_text}})
                    confirmation_sent = True
                
                action_name = cmd.get("action_name")
                repetitions = cmd.get("repetitions", 1)
                sequential_execution_plan_for_bg.append({"type": "perform_action_later", "data": {"action_name": action_name, "repetitions": repetitions}})

            elif cmd_type == "sing_song":
                song_id = cmd.get("song_id")
                # Also give a confirmation for singing
                confirmation_text = "好的，为您播放歌曲！"
                sequential_execution_plan_for_bg.append({"type": "direct_response_for_tts", "data": {"text_to_speak": confirmation_text}})
                sequential_execution_plan_for_bg.append({"type": "sing_song_later", "data": {"song_id": song_id}})

            elif cmd_type == "cancel_singing":
                if ros_publisher_cancel_singing:
                    ros_publisher_cancel_singing.publish(Empty())
                    # Also give a spoken confirmation
                    tts_msg = String()
                    tts_msg.data = "好的，已停止播放。"
                    ros_publisher_tts_input.publish(tts_msg)
                sequential_execution_plan_for_bg = [] # Clear the plan
                break

            elif cmd_type == "query_vision":
                prompt = cmd.get("prompt_for_vision")
                # The response for this will come from image_caption_node, so we just send the question
                sequential_execution_plan_for_bg.append({"type": "query_vision_later", "data": {"prompt_for_vision": prompt}})

            else:
                error_message = cmd.get("message", f"未知的指令类型 '{cmd_type}'")
                primary_text_for_web_display = f"处理时遇到点小麻烦: {error_message}"
                is_error = True
                sequential_execution_plan_for_bg = []
                break
    
    if sequential_execution_plan_for_bg and not is_error:
        ros_node.get_logger().info("启动后台线程处理任务...")
        bg_thread = threading.Thread(target=_handle_sequential_execution_in_background, args=(list(sequential_execution_plan_for_bg),))
        bg_thread.daemon = True
        bg_thread.start()
    elif is_error:
        # If there was an error during parsing, send the error message to the UI
        if primary_text_for_web_display and ros_publisher_tts_input:
            tts_msg = String()
            tts_msg.data = primary_text_for_web_display
            # We publish to /tts_input, and our web_display_callback will catch it
            ros_publisher_tts_input.publish(tts_msg)
        ros_node.get_logger().info("因错误，未执行任何后台指令。")
        
    # This return value is now mainly for the synchronous HTTP response
    return {"is_error": is_error, "display_text": primary_text_for_web_display}


# --- Voice Command Callback ---
def llm_and_action_worker(command_text):
    if not openai_client:
        ros_node.get_logger().error("LLM Worker: Dashscope客户端未初始化，无法处理指令！")
        tts_msg = String()
        tts_msg.data = "抱歉，我的AI大脑没有连接，请检查API密钥。"
        ros_publisher_tts_input.publish(tts_msg)
        return
    parsed_commands = call_intent_parsing_llm(command_text)
    _process_and_execute_llm_commands(parsed_commands)

def process_recognized_text(node, msg, sock):
    command_text = msg.data
    node.get_logger().info(f"从 /recognized_text 收到语音指令: '{command_text}'")
    sock.emit('new_message', {'text': command_text, 'type': 'user-message'})
    worker_thread = threading.Thread(target=llm_and_action_worker, args=(command_text,))
    worker_thread.daemon = True
    worker_thread.start()

# --- HTML Template ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>OriginMan 语音控制台</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
    <style>
        :root { --bg-main: #2F3640; --bg-container: #2a2d35; --bg-chatlog: #252830; --bg-input-area: #313540; --text-primary: #d1d5db; --text-secondary: #9ca3af; --text-title: #e5e7eb; --accent-color: #3b82f6; --accent-hover: #2563eb; --bot-message-bg: #374151; --error-message-bg: #4b1f24; --error-text-color: #fca5a5; --border-color: #4b5563; --border-focus-color: var(--accent-color); --font-family: 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif; --border-radius-sm: 4px; --border-radius-md: 8px; --mic-inactive: #6b7280; --mic-active: #ef4444; --mic-hover: #9ca3af; }
        body {font-family: var(--font-family); margin: 0; padding: 20px; background-color: var(--bg-main); color: var(--text-primary); display: flex; justify-content: center; align-items: flex-start; min-height: 100vh; box-sizing: border-box;}
        .container {background-color: var(--bg-container); padding: 20px 25px; border-radius: var(--border-radius-md); border: 1px solid var(--border-color); width: 100%; max-width: 720px; display: flex; flex-direction: column; height: calc(100vh - 40px); max-height: 900px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);}
        h1 {text-align: center; color: var(--text-title); margin-top: 5px; margin-bottom: 15px; font-weight: 300; font-size: 1.75em; letter-spacing: 0.5px; border-bottom: 1px solid var(--border-color); padding-bottom: 15px;}
        .config-area {margin-bottom: 15px; padding: 15px; background-color: var(--bg-input-area); border-radius: var(--border-radius-sm); border: 1px solid var(--border-color);}
        .config-area label {display: block; margin-bottom: 5px; color: var(--text-secondary); font-size: 0.9em;}
        .config-area input[type="text"] {width: calc(100% - 24px); padding: 8px 10px; margin-bottom: 10px; border-radius: var(--border-radius-sm); border: 1px solid var(--border-color); background-color: var(--bg-chatlog); color: var(--text-primary); font-size: 0.9em;}
        .config-area button {background-color: var(--accent-color); color: white; padding: 8px 15px; border: none; border-radius: var(--border-radius-sm); cursor: pointer; font-size: 0.9em; transition: background-color 0.2s;}
        .config-area button:hover {background-color: var(--accent-hover);}
        #chatLog {flex-grow: 1; margin-bottom: 15px; padding: 15px; background-color: var(--bg-chatlog); border-radius: var(--border-radius-sm); overflow-y: auto; border: 1px solid var(--border-color); display: flex; flex-direction: column; gap: 10px; scrollbar-width: thin; scrollbar-color: var(--border-color) var(--bg-chatlog);}
        .message {padding: 10px 14px; border-radius: var(--border-radius-md); max-width: 80%; word-wrap: break-word; line-height: 1.6; font-size: 0.9em; opacity: 0; transform: translateY(10px); animation: messageFadeIn 0.3s ease-out forwards;}
        @keyframes messageFadeIn {to {opacity: 1; transform: translateY(0);}}
        .user-message {background-color: var(--accent-color); color: white; align-self: flex-end; border-bottom-right-radius: var(--border-radius-sm);}
        .bot-message {background-color: var(--bot-message-bg); color: var(--text-primary); align-self: flex-start; border-bottom-left-radius: var(--border-radius-sm);}
        .error-message {background-color: var(--error-message-bg); color: var(--error-text-color); align-self: flex-start; border-bottom-left-radius: var(--border-radius-sm);}
        .input-area {display: flex; gap: 8px; padding: 10px; background-color: var(--bg-input-area); border-radius: var(--border-radius-md); margin-top: auto; border: 1px solid var(--border-color);}
        textarea#naturalLanguageInput {flex-grow: 1; padding: 10px 12px; border-radius: var(--border-radius-sm); border: 1px solid var(--border-color); background-color: var(--bg-chatlog); color: var(--text-primary); font-size: 0.95em; min-height: 44px; resize: none; outline: none; transition: border-color 0.2s ease-in-out, box-shadow 0.2s ease-in-out;}
        textarea#naturalLanguageInput:focus {border-color: var(--border-focus-color); box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.3);}
        button#sendButton {background-color: var(--accent-color); color: white; padding: 0 20px; border: none; border-radius: var(--border-radius-sm); cursor: pointer; font-size: 0.95em; font-weight: 500; transition: background-color 0.2s ease-in-out; min-height: 44px; display: flex; align-items: center; justify-content: center;}
        button#sendButton:hover {background-color: var(--accent-hover);}
        #micButton { background-color: transparent; border: none; cursor: pointer; padding: 10px; min-height: 44px; display: flex; align-items: center; justify-content: center; }
        #micIcon { width: 24px; height: 24px; color: var(--mic-inactive); transition: color 0.2s; }
        #micButton:hover #micIcon { color: var(--mic-hover); }
        #micButton.recording #micIcon { color: var(--mic-active); }
    </style>
</head>
<body>
    <div class="container">
        <h1>OriginMan语音控制台</h1>
        <div class="config-area">
            <label for="dashscopeApiKeyInput">阿里云 Dashscope API Key:</label>
            <input type="text" id="dashscopeApiKeyInput" placeholder="在此输入或更新 Dashscope API Key">
            <button onclick="saveApiKey()">保存并分发API Key</button>
        </div>
        <div id="chatLog">
            <div class="message bot-message">你好！我是基于多模态大模型的OriginMan助手。请先在上方输入框中设置您的阿里云Dashscope API Key。然后您可以通过键盘输入指令，或点击麦克风按钮与我交流。</div>
        </div>
        <div class="input-area">
            <textarea id="naturalLanguageInput" placeholder="在此输入指令..." rows="1"></textarea>
            <button id="micButton" title="点击开始/停止说话">
                <svg id="micIcon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3zm0 12a5 5 0 0 1-5-5V5a5 5 0 0 1 10 0v6a5 5 0 0 1-5 5z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2H3v2a9 9 0 0 0 8 8.94V23h2v-2.06A9 9 0 0 0 21 12v-2h-2z"/></svg>
            </button>
            <button id="sendButton" onclick="sendNaturalLanguageCommand()">发送</button>
        </div>
    </div>
    <script>
        // ... (All javascript is unchanged from the previous version)
        const socket = io();
        function appendMessage(text, type) { const chatLog = document.getElementById('chatLog'); const messageDiv = document.createElement('div'); messageDiv.classList.add('message', type); messageDiv.textContent = text; chatLog.appendChild(messageDiv); setTimeout(() => { chatLog.scrollTop = chatLog.scrollHeight; }, 50); }
        socket.on('new_message', function(msg) { appendMessage(msg.text, msg.type); });
        async function saveApiKey() { const apiKey = document.getElementById('dashscopeApiKeyInput').value; if (!apiKey.trim()) { alert('请输入有效的API Key。'); return; } appendMessage('正在保存并向所有AI节点分发API Key...', 'bot-message'); try { const response = await fetch('/save_api_key', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dashscope_api_key: apiKey }) }); const result = await response.json(); const messageType = result.status === 'success' ? 'bot-message' : 'error-message'; appendMessage(result.message, messageType); } catch (error) { appendMessage('保存密钥时发生网络错误: ' + error, 'error-message'); } }
        async function sendNaturalLanguageCommand() { const userInputElement = document.getElementById('naturalLanguageInput'); const userInput = userInputElement.value; if (!userInput.trim()) { return; } appendMessage(userInput, 'user-message'); userInputElement.value = ''; userInputElement.focus(); try { const response = await fetch('/execute_natural_language_command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: userInput }) }); if (!response.ok) { const result = await response.json(); const messageType = result.status === '失败' ? 'error-message' : 'bot-message'; const errorText = result.llm_direct_response_text || "发生未知错误"; if (errorText) { appendMessage(errorText, messageType); } } } catch (error) { appendMessage('与机器人通信失败: ' + error.message, 'error-message'); } }
        const micButton = document.getElementById('micButton');
        let isRecording = false;
        micButton.addEventListener('click', toggleRecording);
        async function toggleRecording() { if (!isRecording) { isRecording = true; micButton.classList.add('recording'); appendMessage("请说话... (再次点击麦克风结束)", 'bot-message'); try { await fetch('/start_recording', { method: 'POST' }); } catch (error) { appendMessage('启动录音失败: ' + error.message, 'error-message'); isRecording = false; micButton.classList.remove('recording'); } } else { isRecording = false; micButton.classList.remove('recording'); const chatLog = document.getElementById('chatLog'); const messages = chatLog.getElementsByClassName('bot-message'); for (let i = messages.length - 1; i >= 0; i--) { if (messages[i].textContent.includes("请说话...")) { messages[i].remove(); break; } } appendMessage("正在识别...", 'bot-message'); try { await fetch('/stop_recording', { method: 'POST' }); } catch (error) { appendMessage('停止录音失败: ' + error.message, 'error-message'); } } }
        document.getElementById('naturalLanguageInput').addEventListener('keypress', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendNaturalLanguageCommand(); } });
    </script>
</body>
</html>
"""

# --- Flask Routes ---
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/save_api_key', methods=['POST'])
def save_api_key_route():
    global current_dashscope_api_key, ros_node, param_client_tts, param_client_vision, param_client_voice
    data = request.get_json()
    new_api_key = data.get('dashscope_api_key')
    if not new_api_key or not new_api_key.strip():
        return jsonify({"status": "error", "message": "API Key不能为空"}), 400
    current_dashscope_api_key = new_api_key.strip()
    ros_node.get_logger().info(f"Web界面接收到新的API Key: ...{current_dashscope_api_key[-4:]}")
    initialize_openai_client()
    req = SetParameters.Request()
    param_msg = Parameter('dashscope_api_key', Parameter.Type.STRING, current_dashscope_api_key).to_parameter_msg()
    req.parameters.append(param_msg)
    clients = {"TTS": param_client_tts, "Vision": param_client_vision, "Voice": param_client_voice}
    for name, client in clients.items():
        if client.service_is_ready():
            client.call_async(req)
            ros_node.get_logger().info(f"已向 {name} 节点发送API Key更新请求。")
        else:
            ros_node.get_logger().warn(f"{name} 节点的参数服务不可用，无法发送API Key。")
    return jsonify({"status": "success", "message": "API Key已在Web服务中保存，并已向所有AI节点发送更新请求。"})

@app.route('/start_recording', methods=['POST'])
def start_recording_route():
    if ros_publisher_voice_control:
        ros_publisher_voice_control.publish(String(data="START"))
        ros_node.get_logger().info("Web UI: 'START' recording command sent.")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "ROS publisher not ready"}), 500

@app.route('/stop_recording', methods=['POST'])
def stop_recording_route():
    if ros_publisher_voice_control:
        ros_publisher_voice_control.publish(String(data="STOP"))
        ros_node.get_logger().info("Web UI: 'STOP' recording command sent.")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "ROS publisher not ready"}), 500

@app.route('/execute_natural_language_command', methods=['POST'])
def execute_natural_language_command():
    global current_dashscope_api_key, ros_node
    data = request.get_json()
    user_command_text = data.get('command')
    if not user_command_text: return jsonify({"status": "失败", "error": "未提供指令文本"}), 400
    if not current_dashscope_api_key: 
        return jsonify({"status": "失败", "llm_direct_response_text": "错误: Dashscope API Key 未配置。请先在上方输入框中设置。"}), 400
    if not ros_node: return jsonify({"status": "失败", "llm_direct_response_text": "错误: ROS节点服务未就绪。"}), 500
    worker_thread = threading.Thread(target=llm_and_action_worker, args=(user_command_text,))
    worker_thread.daemon = True
    worker_thread.start()
    return jsonify({"status": "已接收处理"}), 200

# --- Main function and ROS Spin Thread ---
def ros_spin_thread_func(node_to_spin):
    executor = MultiThreadedExecutor()
    executor.add_node(node_to_spin)
    logger = node_to_spin.get_logger()
    logger.info("ROS Spin线程已启动。")
    try:
        executor.spin()
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        logger.info("ROS Spin线程收到关闭信号。")
    finally:
        logger.info("ROS Spin线程已结束。")

def main(args=None): 
    global ros_node 
    rclpy.init(args=args) 
    init_ros() 
    if not ros_node:
        print("严重错误: ROS节点未能初始化。程序退出。", file=sys.stderr)
        if rclpy.ok(): rclpy.shutdown()
        return
    ros_thread = threading.Thread(target=ros_spin_thread_func, args=(ros_node,), daemon=True)
    ros_thread.start()
    ros_node.get_logger().info("启动Flask Web服务器, 网页地址为机器人IP:5000")
    try:
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except Exception as e:
        ros_node.get_logger().fatal(f"Web服务器发生严重错误: {e}", exc_info=True)
    finally:
        if ros_node and rclpy.ok() and not ros_node._is_shutdown:
            ros_node.get_logger().info("请求关闭Web接口ROS节点...")
            ros_node.destroy_node() 
        if rclpy.ok(): rclpy.shutdown()
        print("Web接口服务已关闭。")

if __name__ == '__main__':
    main()