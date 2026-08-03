#!/usr/bin/env python3
# _VLA_PATH_BOOTSTRAP
# 让 vendored 依赖（根目录的 edge_tts/aiohttp 等、_vendor 的 vosk）在任何调用方式下都可导入
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.path.dirname(_HERE)
for _p in (_ROOT, _os.path.join(_ROOT, '_vendor')):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
# end path bootstrap

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
import wave as _wave
import tempfile
import numpy as np
import pyaudio
import webrtcvad

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



# ===== 语音播报文案 =====
WELCOME_MSG = '你好呀，我是你的AI机器人有什么要我帮你的吗，如果不想用我了可以对我说退出或者在终端输入quit，我就退下'
QUOTA_MSG = '我AI额度用光了，叫我主人给我充点钱，才能用我噢'
BROKEN_MSG = '我这个功能好像坏了，请叫技术员把我修好'
GOODBYE_MSG = '拜拜，下次见'

# 退出指令关键词（语音/文本均生效）
EXIT_KEYWORDS = ('exit', 'quit', '退出', '退下', '离开', '再见', '拜拜')


def _speak_text(text, audio_device=None):
    """独立语音播报：edge_tts 合成 -> ffmpeg 转 wav -> aplay 播放。不依赖节点实例。"""
    text = (text or '').strip()
    if not text:
        return
    if audio_device is None:
        audio_device = os.environ.get('AUDIO_DEVICE', 'plughw:0,0')
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        wav_data = loop.run_until_complete(_edge_tts_synthesize(text))
        loop.close()
        if wav_data:
            result = subprocess.run(['aplay', '-D', audio_device, '-'], input=wav_data)
            if result.returncode != 0:
                print('aplay 播放失败。')
        else:
            print('音频数据为空。')
    except Exception as e:
        print(f'语音合成播放失败: {e}')


async def _edge_tts_synthesize(text):
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

class SherpaASR:
    """离线语音转文字（sherpa-onnx Paraformer 中文模型 + webrtcvad 端点检测）。
    sherpa-onnx 即 py-xiaozhi 所用的同款语音引擎；此处用其完整 ASR（非唤醒词）。
    自包含：sherpa_onnx 位于 originman_hu/_vendor，模型位于 originman_hu/sherpa_models，
    无需联网、无需 API key。录音与降噪流程沿用 originman asr_node 的成熟方案。"""

    def __init__(self, audio_device='hw:0,0', model_dir=None, verbose=True):
        import sys as _sys
        _here = os.path.dirname(os.path.abspath(__file__))
        _vendor = os.path.normpath(os.path.join(_here, '..', '_vendor'))
        if os.path.isdir(_vendor) and _vendor not in _sys.path:
            _sys.path.insert(0, _vendor)
        try:
            import sherpa_onnx
        except Exception as e:
            raise RuntimeError(f'无法导入 sherpa_onnx（{e}），请检查 originman_hu/_vendor/sherpa_onnx')

        if model_dir is None:
            model_dir = os.path.normpath(os.path.join(_here, '..', 'sherpa_models', 'paraformer-zh'))
        model_onnx = os.path.join(model_dir, 'model.int8.onnx')
        tokens = os.path.join(model_dir, 'tokens.txt')
        if not os.path.isfile(model_onnx) or not os.path.isfile(tokens):
            raise RuntimeError(f'未找到 sherpa 模型文件：{model_onnx} / {tokens}')

        self.recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
            paraformer=model_onnx,
            tokens=tokens,
            num_threads=2,
            sample_rate=16000,
            decoding_method='greedy_search',
            provider='cpu',
        )
        self.audio_device = audio_device
        self.verbose = verbose
        # 录音参数（沿用 asr_node 的成熟配置）
        self.channels = 2
        self.in_rate = 48000
        self.out_rate = 16000
        self.sample_format = pyaudio.paInt16
        self.chunk = 960            # 48k 下 20ms，webrtcvad 支持的帧长
        self.vad_mode = 1
        self.silence_threshold = 75
        self.noise_reduction_factor = 0.5
        self.timeout = 8
        self._pa = pyaudio.PyAudio()
        self._vad = webrtcvad.Vad(self.vad_mode)

    def _find_device(self):
        for i in range(self._pa.get_device_count()):
            info = self._pa.get_device_info_by_index(i)
            if self.audio_device in info.get('name', ''):
                return i
        try:
            return self._pa.get_default_input_device_info()['index']
        except Exception:
            return None

    def _record_utterance(self):
        """用 VAD 录一句话，返回 16k 单声道 wav 文件路径；未录到返回 None。"""
        dev = self._find_device()
        stream = self._pa.open(format=self.sample_format, channels=self.channels,
                               rate=self.in_rate, input=True,
                               input_device_index=dev, frames_per_buffer=self.chunk)
        frames = []
        try:
            noise_frames = []
            for _ in range(50):
                noise_frames.append(np.frombuffer(stream.read(self.chunk, exception_on_overflow=False), dtype=np.int16))
            noise_profile = np.mean(np.concatenate(noise_frames), axis=0)

            if self.verbose:
                print('[语音] 请说话…')
            silence_count = 0
            speech_started = False
            start = time.time()
            while True:
                if time.time() - start > self.timeout:
                    break
                data = stream.read(self.chunk, exception_on_overflow=False)
                chunk_np = np.frombuffer(data, dtype=np.int16)
                denoised = chunk_np - (noise_profile * self.noise_reduction_factor)
                denoised_bytes = denoised.astype(np.int16).tobytes()
                mono = np.mean(np.frombuffer(denoised_bytes, dtype=np.int16).reshape(-1, self.channels), axis=1).astype(np.int16)
                if self._vad.is_speech(mono.tobytes(), self.in_rate):
                    silence_count = 0
                    if not speech_started:
                        speech_started = True
                        if self.verbose:
                            print('[语音] 检测到说话…')
                    frames.append(denoised_bytes)
                elif speech_started:
                    silence_count += 1
                    frames.append(denoised_bytes)
                    if silence_count > self.silence_threshold:
                        break
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass

        if not frames:
            return None

        raw_path = tempfile.mktemp(suffix='.wav')
        wf = _wave.open(raw_path, 'wb')
        wf.setnchannels(self.channels)
        wf.setsampwidth(self._pa.get_sample_size(self.sample_format))
        wf.setframerate(self.in_rate)
        wf.writeframes(b''.join(frames))
        wf.close()

        out_path = raw_path + '.16k.wav'
        result = subprocess.run(
            ['ffmpeg', '-y', '-i', raw_path, '-ac', '1', '-ar', str(self.out_rate),
             '-f', 'wav', '-acodec', 'pcm_s16le', out_path],
            capture_output=True)
        os.remove(raw_path)
        if result.returncode != 0 or not os.path.exists(out_path):
            if os.path.exists(out_path):
                os.remove(out_path)
            return None
        return out_path

    def listen(self):
        """录一句话并返回识别文本（可能为空字符串）。"""
        wav_path = self._record_utterance()
        if not wav_path:
            if self.verbose:
                print('[语音] 未检测到有效语音。')
            return ''
        wf = None
        try:
            stream = self.recognizer.create_stream()
            wf = _wave.open(wav_path, 'rb')
            frames = wf.readframes(wf.getnframes())
            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            stream.accept_waveform(self.out_rate, samples)
            self.recognizer.decode_stream(stream)
            text = stream.result.text.strip()
            if self.verbose:
                print(f'[语音] 识别结果：{text}')
            return text
        except Exception as e:
            if self.verbose:
                print(f'[语音] 识别异常：{e}')
            return ''
        finally:
            if wf is not None:
                try:
                    wf.close()
                except Exception:
                    pass
            if os.path.exists(wav_path):
                os.remove(wav_path)

    def close(self):
        try:
            self._pa.terminate()
        except Exception:
            pass


class VisionIntegratedChat:
    def __init__(self):
        self.camera_index = int(os.environ.get('VISION_CAMERA_INDEX', '0'))
        self.api_key = os.environ.get('ARK_API_KEY', '')
        self.audio_device = os.environ.get('AUDIO_DEVICE', 'plughw:0,0')
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.running = True
        self.ai_enabled = True
        self.ai_quota_exhausted = False
        self._exit_reason = None
        self.input_mode = os.environ.get('VISION_INPUT_MODE', 'text').strip().lower()
        self.asr = None
        if self.input_mode in ('voice', 'hybrid'):
            try:
                self.asr = SherpaASR(audio_device=os.environ.get('VISION_ASR_DEVICE', 'hw:0,0'))
                print(f'语音输入已启用（模式：{self.input_mode}），sherpa-onnx 离线识别就绪。')
            except Exception as e:
                print(f'警告：语音识别初始化失败，回退到文本输入：{e}')
                self.input_mode = 'text'
                self.asr = None

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
                user_input = ''
                if self.input_mode in ('voice', 'hybrid') and self.asr is not None:
                    if self.input_mode == 'hybrid':
                        try:
                            typed = input('\n[输入文本指令，或直接回车说话]: ').strip()
                        except (EOFError, KeyboardInterrupt):
                            break
                        except Exception:
                            typed = ''
                        user_input = typed if typed else self.asr.listen()
                    else:
                        user_input = self.asr.listen()
                else:
                    try:
                        user_input = input('\n[请输入文本指令]: ').strip()
                    except (EOFError, KeyboardInterrupt):
                        break
                    except Exception:
                        continue

                if not user_input:
                    continue
                if self._is_exit_command(user_input):
                    print('收到退出指令，退出程序')
                    self._exit_reason = 'command'
                    break

                self.process_query(user_input)
                if not self.running:
                    break
        finally:
            self.ai_enabled = False
            if self._exit_reason != 'quota':
                _speak_text(GOODBYE_MSG, self.audio_device)
            self.shutdown()

    def process_query(self, text):
        print(f'\n正在处理指令：{text}')
        if not self.ai_enabled:
            print('AI 已停用，跳过本次请求。')
            return
        
        query_frame = self._get_frame_for_query()
        if query_frame is None:
            print('警告：当前没有可用的图像帧')
            return

        image_base64 = self._encode_frame_to_base64(query_frame)

        payload = {
            'model': 'doubao-seed-2-0-pro-260215',
            'tools': [{'type': 'web_search', 'max_keyword': 2, 'limit': 10}],
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
        if self.ai_quota_exhausted:
            print('AI 额度已用完，退出。')
            self._exit_reason = 'quota'
            self.running = False
            _speak_text(QUOTA_MSG, self.audio_device)
            return
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
    
    def check_ai_health(self):
        """启动期最小化 AI 健康检查：验证连通性与额度。返回 'ok'/'quota'/'error'。"""
        if not self.api_key:
            return 'error'
        payload = {
            'model': 'doubao-seed-2-0-pro-260215',
            'thinking': {'type': 'disabled'},
            'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': '你好'}]}],
        }
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            'https://ark.cn-beijing.volces.com/api/v3/responses',
            data=data, method='POST',
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {self.api_key}'})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                resp.read()
                return 'ok'
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')
            if e.code == 429 or 'AccountQuotaExceeded' in body or 'quota' in body.lower():
                return 'quota'
            return 'error'
        except Exception:
            return 'error'

    def _is_exit_command(self, text):
        """判断是否为退出指令（兼容语音口语化表达与英文）。"""
        t = (text or '').strip()
        if not t:
            return False
        low = t.lower()
        # 英文按词匹配
        if any(w in EXIT_KEYWORDS for w in low.split()):
            return True
        # 中文：清理语气词/标点
        for ch in '。！.!?啊吧了呢~，,、哈呀嘛':
            low = low.replace(ch, '')
        low = low.strip()
        if not low:
            return False
        # 1) 整句就是关键词
        for kw in EXIT_KEYWORDS:
            if low == kw:
                return True
        # 2) 短句（<=8字）含关键词 -> 退出（口语如“那我就离开了”）
        if len(low) <= 8:
            for kw in EXIT_KEYWORDS:
                if kw in low:
                    return True
        # 3) 以“我想/我要/请”+退出词 开头/结尾
        for kw in EXIT_KEYWORDS:
            if low.startswith('我想'+kw) or low.startswith('我要'+kw) or low.startswith('请'+kw) or low.endswith(kw):
                return True
        return False

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
            body = e.read().decode('utf-8', 'replace')
            print(f'视觉模型 HTTP 错误: {e.code} {e.reason}')
            if e.code == 429 or 'AccountQuotaExceeded' in body or 'quota' in body.lower():
                self.ai_quota_exhausted = True
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
        _speak_text(text, self.audio_device)

    def shutdown(self):
        self.running = False
        self.ai_enabled = False
        if self.cap is not None and self.cap.isOpened():
            self.cap.release()
        if self.asr is not None:
            self.asr.close()


def main():
    # 1. 构造节点（摄像头 + 语音识别初始化）
    try:
        node = VisionIntegratedChat()
    except Exception as e:
        print(f'启动失败: {e}')
        _speak_text(BROKEN_MSG)
        return

    # 2. AI 连通性与额度健康检查
    status = node.check_ai_health()
    if status == 'quota':
        print('AI 额度已用完，无法启动。')
        _speak_text(QUOTA_MSG, node.audio_device)
        node.shutdown()
        return
    if status != 'ok':
        print('AI 服务不可用，无法启动。')
        _speak_text(BROKEN_MSG, node.audio_device)
        node.shutdown()
        return

    # 3. 成功进入模式：欢迎语 + 主循环
    _speak_text(WELCOME_MSG, node.audio_device)
    try:
        node.run()
    except Exception as e:
        print(f'运行异常: {e}')


if __name__ == '__main__':
    main()


