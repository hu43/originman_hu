#!/usr/bin/env python3
import ast
import asyncio
import base64
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request

import cv2
import edge_tts

import hiwonder.ActionGroupControl as AGC

robot_order_template = '''
你是我的机器人助手，请根据摄像头画面和用户指令，生成机器人要执行的动作和一句简短中文回复。
你只需要输出一个 JSON 对象，不要输出任何解释性文字、不要输出代码块标记、不要输出多余文本。
返回结果格式如下：
{"action": [...], "response": "..."}

【可用函数列表】
站立：stand()
原地踏步：stepping()
前进一步：move_forward()
后退一步：move_back()
向左平移移动一步：move_left()
向右平移移动一步：move_right()
向左旋转移动：turn_left()
向右旋转移动：turn_right()
鞠躬：bow()
挥手打招呼：wave()
扭腰：twist()
捶胸庆祝：celebrate()
下蹲：squat()
踢右脚：right_shot()
踢左脚：left_shot()
仰卧起坐：sit_ups()
佛山叶问的咏春拳：wing_chun()
从前倾趴卧起立：stand_up_front()
从后仰躺倒起立：stand_up_back()


【输出限制】
- 直接输出json即可，从{开始，以}结束，不要输出```json的开头或结尾
- action 值必须是一个字符串列表，列表元素顺序表示执行顺序
- action 中函数名必须使用上面定义的函数，kickball 和 transport 参数必须用双引号
- response 需要是中文简短回答，不超过20个字，幽默、善意、玩梗、有趣，不要回复英文
- 如果没有动作，请返回 action: []
- 如果我让你从躺倒状态站起来，你回复一些和"躺平"相关的话

【示例】
用户指令：请先鞠躬，然后挥手。
返回：{"action":["bow()", "wave()"], "response":"敬个礼挥挥手，你是我的好朋友"}

现在请根据下面的摄像头画面和用户问题生成结果：
'''


def stand(): AGC.runActionGroup('stand')
def move_forward(): AGC.runActionGroup('go_forward')
def move_back(): AGC.runActionGroup('back_fast')
def move_left(): AGC.runActionGroup('left_move_fast')
def move_right(): AGC.runActionGroup('right_move_fast')
def turn_left(): AGC.runActionGroup('turn_left')
def turn_right(): AGC.runActionGroup('turn_right')
def bow(): AGC.runActionGroup('bow')
def wave(): AGC.runActionGroup('wave')
def twist(): AGC.runActionGroup('twist')
def celebrate(): AGC.runActionGroup('chest')
def squat(): AGC.runActionGroup('squat')
def right_shot(): AGC.runActionGroup('right_shot_fast')
def left_shot(): AGC.runActionGroup('left_shot_fast')
def sit_ups(): AGC.runActionGroup('sit_ups')
def stepping(): AGC.runActionGroup('stepping')
def wing_chun(): AGC.runActionGroup('wing_chun')
def stand_up_front(): AGC.runActionGroup('stand_up_front')
def stand_up_back(): AGC.runActionGroup('stand_up_back')
# def athletics(): os.system('python3 /userdata/dev_ws/src/originman/originman_hu/TonyPi-API-20241116_no_key/TonyPi/备份代码/athletics_perform_only.py')
# def kickball(color='red'): os.system(f'python3 /userdata/dev_ws/src/originman/originman_hu/TonyPi-API-20241116_no_key/TonyPi/备份代码/KickBall_only_once.py {color}')
# def transport(color_list_str='red green blue'):
#     color_list = color_list_str.split(' ')
#     os.system(f'python3 /userdata/dev_ws/src/originman/originman_hu/TonyPi-API-20241116_no_key/TonyPi/备份代码/Transport_only.py "{color_list}"')

ACTION_FUNCS = {
    'stand': stand,
    'move_forward': move_forward,
    'move_back': move_back,
    'move_left': move_left,
    'move_right': move_right,
    'turn_left': turn_left,
    'turn_right': turn_right,
    'bow': bow,
    'wave': wave,
    'twist': twist,
    'celebrate': celebrate,
    'squat': squat,
    'right_shot': right_shot,
    'left_shot': left_shot,
    'sit_ups': sit_ups,
    'stepping': stepping,
    'wing_chun': wing_chun,
    'stand_up_front': stand_up_front,
    'stand_up_back': stand_up_back,
    # 'athletics': athletics,
    # 'kickball': kickball,
    # 'transport': transport,
}


class VisionIntegratedChat:
    def __init__(self):
        self.camera_index = int(os.environ.get('VISION_CAMERA_INDEX', '0'))
        self.api_key = os.environ.get('ARK_API_KEY', os.environ.get('DOUBAO_API_KEY', 'ark-fc4685b1-f775-4bb4-9c7a-7d8670569338-a63a9'))
        self.audio_device = os.environ.get('AUDIO_DEVICE', 'plughw:0,0')
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.running = True

        # 摄像头索引：优先环境变量，未设置则自动探测
        camera_index_env = os.environ.get('VISION_CAMERA_INDEX')
        if camera_index_env is not None:
            self.camera_index = int(camera_index_env)
        else:
            print('未指定摄像头索引，正在自动探测可用摄像头...')
            detected = self._auto_detect_camera_index()
            if detected is None:
                raise RuntimeError('未探测到任何可用摄像头，请检查硬件连接与驱动。')
            self.camera_index = detected
            print(f'自动探测到可用摄像头：索引 {self.camera_index}（/dev/video{self.camera_index}）')

        # 强制使用 V4L2 后端打开，Linux 下兼容性最稳定
        self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(f'无法打开摄像头索引 {self.camera_index}，请检查摄像头连接与权限。')

        # 设置通用兼容分辨率，绝大多数USB摄像头都支持
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        self.capture_thread = threading.Thread(target=self._camera_loop, daemon=True)
        self.capture_thread.start()

        print('视觉整合聊天节点已启动。')
        print('输入文本指令，程序会自动调用摄像头并将画面发送给大模型。')
        print('输入 exit 或 quit 退出程序。')
        if not self.api_key:
            print('警告：未检测到 ARK_API_KEY / DOUBAO_API_KEY，API 请求将失败。')

    def _auto_detect_camera_index(self, max_index=5):
        """自动探测第一个可用的摄像头索引，强制使用V4L2后端验证"""
        for idx in range(max_index):
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            if cap.isOpened():
                cap.release()
                return idx
        return None

    def _camera_loop(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                with self.frame_lock:
                    self.latest_frame = frame.copy()
            time.sleep(0.1)
    
    def _get_frame_for_query(self):
        with self.frame_lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
        return None

    def run(self):
        try:
            while self.running:
                try:
                    user_input = input('\n[输入文本指令]：').strip()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    break
                except Exception:
                    continue

                if not user_input:
                    continue
                if user_input.lower() in ('exit', 'quit'):
                    print('退出程序。')
                    break

                self.process_query(user_input)
        finally:
            self.shutdown()

    def process_query(self, text):
        print(f'\n正在处理指令：{text}')
        
        query_frame = self._get_frame_for_query()
        if query_frame is None:
            print('警告：当前没有可用的图像帧')
            return

        image_base64 = self._encode_frame_to_base64(query_frame)

        payload = {
            'model': 'doubao-seed-2-0-pro-260215',
            'tools': [{'type': 'web_search'}],
            'thinking': {'type': 'disabled'},
            'input': [
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'input_image',
                            'image_url': f'data:image/jpeg;base64,{image_base64}' if image_base64 else ''
                        },
                        {
                            'type': 'input_text',
                            'text': robot_order_template + text,
                        },
                    ],
                }
            ],
        }

        response_text = self._call_vision_model(payload)
        if not response_text:
            print('未获得大模型有效响应。')
            return

        parsed = self._parse_action_response(response_text)
        if not parsed:
            print('无法解析大模型返回内容，原始输出：')
            print(response_text)
            return

        actions = parsed.get('action', [])
        response = parsed.get('response', '')

        print('\n[模型回复文本]:', response)
        print('[模型动作列表]:', actions)

        if response:
            self._synthesize_and_play(response)

        for action_str in actions:
            try:
                print(f'执行动作: {action_str}')
                eval(action_str, {'__builtins__': None}, ACTION_FUNCS)
            except Exception as e:
                print(f'动作执行失败 {action_str}: {e}')
    
    def _encode_frame_to_base64(self, frame) -> str:
        if frame is None:
            return ''
        success, buffer = cv2.imencode('.jpg', frame)
        if not success:
            print('警告：图像编码失败')
            return ''
        return base64.b64encode(buffer.tobytes()).decode('utf-8')

    def _call_vision_model(self, payload: dict) -> str:
        if not self.api_key:
            print('错误：ARK_API_KEY / DOUBAO_API_KEY 未设置')
            return ''

        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            'https://ark.cn-beijing.volces.com/api/v3/responses',
            data=data,
            method='POST',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}',
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode('utf-8')
                parsed = json.loads(body)
                print('模型原始返回：', parsed)
                return self._extract_text_from_response(parsed)
        except urllib.error.HTTPError as e:
            print(f'视觉模型 HTTP 错误: {e.code} {e.reason}')
        except urllib.error.URLError as e:
            print(f'视觉模型网络错误: {e.reason}')
        except Exception as e:
            print(f'视觉模型调用失败: {e}')
        return ''

    def _parse_action_response(self, raw_text: str):
        clean = raw_text.strip()
        
        if clean.startswith('```json'):
            clean = clean[7:].strip()
        elif clean.startswith('```'):
            clean = clean[3:].strip()
        
        if clean.endswith('```'):
            clean = clean[:-3].strip()
        
        parsed = None
        try:
            parsed = json.loads(clean)
        except Exception:
            try:
                parsed = ast.literal_eval(clean)
            except Exception:
                parsed = None

        if parsed is None:
            start = clean.find('{')
            end = clean.rfind('}')
            if start != -1 and end != -1 and end > start:
                snippet = clean[start:end + 1]
                try:
                    parsed = json.loads(snippet)
                except Exception:
                    try:
                        parsed = ast.literal_eval(snippet)
                    except Exception:
                        parsed = None

        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]
        if isinstance(parsed, dict):
            return parsed
        return None

    def _extract_text_from_response(self, data) -> str:
        if not isinstance(data, dict):
            return ''

        raw_text = ''

        if 'output' in data:
            output = data['output']
            if isinstance(output, str):
                raw_text = output.strip()
            elif isinstance(output, list):
                for item in output:
                    if isinstance(item, dict):
                        if item.get('type') == 'message':
                            content = item.get('content', [])
                            if isinstance(content, list):
                                for content_item in content:
                                    if isinstance(content_item, dict) and content_item.get('type') == 'output_text':
                                        raw_text = str(content_item.get('text', '')).strip()
                                        break
                                if raw_text:
                                    break
                            elif isinstance(content, str):
                                raw_text = content.strip()
                                break
                        elif 'content' in item:
                            content = item['content']
                            if isinstance(content, str):
                                raw_text = content.strip()
                                break
                            elif isinstance(content, list):
                                raw_text = self._extract_content_list(content)
                                break
                        elif 'text' in item:
                            raw_text = str(item['text']).strip()
                            break
        if not raw_text and 'choices' in data and isinstance(data['choices'], list) and data['choices']:
            choice = data['choices'][0]
            if isinstance(choice, dict):
                if 'message' in choice and isinstance(choice['message'], dict):
                    content = choice['message'].get('content', '')
                    if isinstance(content, str):
                        raw_text = content.strip()
                    elif isinstance(content, list):
                        raw_text = self._extract_content_list(content)
                elif 'output_text' in choice:
                    raw_text = str(choice['output_text']).strip()
        if not raw_text and 'response' in data and isinstance(data['response'], str):
            raw_text = data['response'].strip()
        if not raw_text:
            raw_text = str(data)

        return raw_text

    def _extract_content_list(self, content_list):
        result = []
        for item in content_list:
            if isinstance(item, dict):
                if 'text' in item:
                    result.append(str(item['text']))
                elif 'content' in item:
                    result.append(str(item['content']))
            elif isinstance(item, str):
                result.append(item)
        return ''.join(result)

    def _synthesize_and_play(self, text):
        if not text.strip():
            return
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            wav_data = loop.run_until_complete(self._edge_tts_synthesize(text))
            loop.close()

            if wav_data:
                cmd = ['aplay', '-D', self.audio_device, '-']
                result = subprocess.run(cmd, input=wav_data)
                if result.returncode != 0:
                    print('aplay 播放失败。')
            else:
                print('音频数据为空。')
        except Exception as e:
            print(f'语音合成播放失败: {e}')

    async def _edge_tts_synthesize(self, text):
        communicate = edge_tts.Communicate(text, 'zh-CN-XiaoyiNeural')
        mp3_data = bytearray()
        async for chunk in communicate.stream():
            if chunk['type'] == 'audio':
                mp3_data.extend(chunk['data'])

        result = subprocess.run(
            ['ffmpeg', '-i', 'pipe:0', '-f', 'wav', '-acodec', 'pcm_s16le', '-ar', '24000', 'pipe:1'],
            input=bytes(mp3_data),
            capture_output=True,
        )
        if result.returncode != 0:
            print(f'ffmpeg 转换失败: {result.stderr.decode()}')
            return b''
        return result.stdout

    def shutdown(self):
        self.running = False
        if self.cap is not None and self.cap.isOpened():
            self.cap.release()


def main():
    try:
        node = VisionIntegratedChat()
        node.run()
    except Exception as e:
        print(f'启动失败: {e}')


if __name__ == '__main__':
    main()


