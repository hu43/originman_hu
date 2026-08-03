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
import rclpy
from cv_bridge import CvBridge, CvBridgeError
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

# 尝试导入集成节点中的动作函数以便复用（若不可用则降级为 no-op）
try:
    import integrated_chat_node as icn
    ACTION_FUNCS = {
        'stand': icn.stand,
        'move_forward': icn.move_forward,
        'move_back': icn.move_back,
        'move_left': icn.move_left,
        'move_right': icn.move_right,
        'turn_left': icn.turn_left,
        'turn_right': icn.turn_right,
        'bow': icn.bow,
        'wave': icn.wave,
        'twist': icn.twist,
        'celebrate': icn.celebrate,
        'squat': icn.squat,
        'right_shot': icn.right_shot,
        'left_shot': icn.left_shot,
        'sit_ups': icn.sit_ups,
        'stepping': icn.stepping,
        'wing_chun': icn.wing_chun,
        'stand_up_front': icn.stand_up_front,
        'stand_up_back': icn.stand_up_back,
        'athletics': icn.athletics,
        'kickball': icn.kickball,
        'transport': icn.transport,
    }
except Exception:
    ACTION_FUNCS = {}


class VisionChatNode(Node):
    def __init__(self):
        super().__init__('vision_chat_node')

        self.declare_parameter('camera_index', 0)
        self.declare_parameter('publish_frequency', 5.0)
        self.declare_parameter('vision_question_topic', '/vision_question')
        self.declare_parameter('image_topic', '/image_raw')
        self.declare_parameter('response_topic', '/tts_input')

        self.camera_index = self.get_parameter('camera_index').get_parameter_value().integer_value
        publish_frequency = self.get_parameter('publish_frequency').get_parameter_value().double_value
        self.image_topic = self.get_parameter('image_topic').get_parameter_value().string_value
        question_topic = self.get_parameter('vision_question_topic').get_parameter_value().string_value
        response_topic = self.get_parameter('response_topic').get_parameter_value().string_value

        if publish_frequency <= 0:
            self.get_logger().warn('发布频率必须大于 0，使用默认 5.0 Hz。')
            publish_frequency = 5.0

        self.api_key = os.environ.get('ARK_API_KEY', '')
        if not self.api_key:
            self.get_logger().warn(
                '没有检测到 ARK_API_KEY 或 DOUBAO_API_KEY 环境变量，视觉大模型请求可能失败。'
            )

        self.declare_parameter('text_model', 'doubao-seed-2-0-pro-260215')
        self.text_model = self.get_parameter('text_model').get_parameter_value().string_value

        self.bridge = CvBridge()
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.processing_lock = threading.Lock()
        
        self.audio_device = "plughw:0,0"

        self.image_publisher = self.create_publisher(Image, self.image_topic, 10)
        self.description_publisher = self.create_publisher(String, response_topic, 10)
        self.vision_answer_publisher = self.create_publisher(String, '/vision_answer', 10)

        self.question_subscription = self.create_subscription(
            String,
            question_topic,
            self.vision_question_callback,
            10,
        )

        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            self.get_logger().error(
                f'无法打开摄像头索引 {self.camera_index}。请检查摄像头是否连接或索引是否正确。'
            )
            return

        timer_period = 1.0 / publish_frequency
        self.timer = self.create_timer(timer_period, self.publish_image)

        self.get_logger().info(f'视觉问答节点已启动。')
        self.get_logger().info(f'  摄像头索引: {self.camera_index}')
        self.get_logger().info(f'  图像将以 {publish_frequency} Hz 发布到 {self.image_topic}')
        self.get_logger().info(f'  视觉问题订阅: {question_topic}')
        self.get_logger().info(f'  生成回答发布: {response_topic} 和 /vision_answer')

        # 启动 CLI 输入线程以便直接在终端输入视觉/文本问题
        self.cli_thread = threading.Thread(target=self._cli_input_loop, daemon=True)
        self.cli_thread.start()

    def publish_image(self):
        ret, frame = self.cap.read()
        if not ret:
            self.get_logger().warn('无法从摄像头读取图像帧。')
            return

        with self.frame_lock:
            self.latest_frame = frame.copy()

        try:
            image_msg = self.bridge.cv2_to_imgmsg(frame, 'bgr8')
            image_msg.header.stamp = self.get_clock().now().to_msg()
            image_msg.header.frame_id = 'camera_optical_frame'
            self.image_publisher.publish(image_msg)
        except CvBridgeError as e:
            self.get_logger().error(f'CvBridge 转换失败: {e}')
        except Exception as e:
            self.get_logger().error(f'发布图像时发生异常: {e}')

    def vision_question_callback(self, msg: String):
        question_text = msg.data.strip()
        if not question_text:
            self.get_logger().info('收到空视觉问题，忽略。')
            return

        self.get_logger().info(f'收到视觉问题: {question_text}')

        if not self.processing_lock.acquire(blocking=False):
            self.get_logger().warn('先前的视觉请求仍在处理，请稍后再试。')
            return

        try:
            frame = None
            with self.frame_lock:
                if self.latest_frame is not None:
                    frame = self.latest_frame.copy()

            if frame is None:
                self.get_logger().warn('当前没有可用的图像帧用于视觉问答。')
                self._publish_description('抱歉，我暂时无法获取到摄像头画面。')
                return

            _, buffer = cv2.imencode('.jpg', frame)
            image_base64 = base64.b64encode(buffer).decode('utf-8')

            
            prompt_text = (
                #'不要超过20个字，中文回复，幽默有趣，不要回复英文。'
                '请简洁回答用户问题，中文回复，只用短句，不要回复英文，不啰嗦、不解释、不反问，幽默自然。直接给答案，禁止主动延伸、禁止多余情绪词、禁止长句。'
                f' 用户的问题是："{question_text}"'
              
            )
            payload = {
                'model': 'doubao-seed-2-0-pro-260215',
                'tools': [{'type': 'web_search'}],
                'thinking': {
                    'type': 'disabled'  # 强制关闭深度思考，不输出推理过程
                },
                'input': [
                    {
                        'role': 'user',
                        'content': [
                            {
                                'type': 'input_image',
                                'image_url': f'data:image/jpeg;base64,{image_base64}'
                            },
                            {
                                'type': 'input_text',
                                'text': prompt_text,
                            },
                        ],
                    }
                ],
            }
           
            answer = self._call_vision_model(payload)
            if not answer:
                answer = '抱歉，我暂时无法理解当前画面。'
            # else:
            #     # 尝试解析 JSON，只提取 response 里的纯中文
            #     try:
            #         import json
            #         answer_data = json.loads(answer)
            #         answer = answer_data.get('response', answer)
            #     except Exception:
            #         # 解析失败就用原文，不崩溃
            #         pass
            self._publish_description(answer)
            # 尝试从模型回答中解析并执行动作（如果模型返回规范化的 JSON 指令）
            try:
                self._maybe_execute_actions_from_text(answer)
            except Exception as e:
                self.get_logger().debug(f'动作解析/执行失败（可忽略）: {e}')
        finally:
            self.processing_lock.release()

    def _cli_input_loop(self):
        """从命令行读取用户输入，直接触发视觉问答与动作执行。"""
        while rclpy.ok():
            try:
                user_input = input('\n[Vision CLI] 请输入问题或命令 (exit 退出): ').strip()
            except EOFError:
                break
            except Exception:
                continue

            if not user_input:
                continue
            if user_input.lower() in ('exit', 'quit'):
                self.get_logger().info('CLI 请求退出，关闭 ROS...')
                try:
                    rclpy.shutdown()
                except Exception:
                    pass
                break

            # 将 CLI 输入视为视觉问题并处理
            try:
                # reuse vision question handler logic
                fake_msg = String()
                fake_msg.data = user_input
                # small delay to ensure a frame is captured at startup
                time.sleep(0.05)
                self.vision_question_callback(fake_msg)
            except Exception as e:
                self.get_logger().error(f'处理 CLI 输入出错: {e}')

    def _maybe_execute_actions_from_text(self, text: str):
        """尝试从模型文本中解析动作列表并执行。支持 JSON 或 Python 单引号形式。"""
        if not text:
            return

        clean = text.strip()
        # 处理可能被 ``` 包裹的情况
        if clean.startswith('```'):
            # 去掉三引号包裹
            try:
                clean = clean.split('```', 2)[1].strip()
            except Exception:
                pass

        parsed = None
        # 尝试 JSON 解析
        try:
            parsed = json.loads(clean)
        except Exception:
            try:
                parsed = ast.literal_eval(clean)
            except Exception:
                parsed = None

        if not parsed:
            return

        # 兼容返回为列表或字典
        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]

        if not isinstance(parsed, dict):
            return

        actions = parsed.get('action', [])
        response_text = parsed.get('response', '')

        if response_text:
            # 发布到 TTS 话题
            msg = String()
            msg.data = response_text
            self.description_publisher.publish(msg)

        if not actions:
            return

        for act in actions:
            try:
                # act 可能是函数调用字符串，例如 "wave()" 或 "kickball('red')"
                self.get_logger().info(f'执行动作: {act}')
                # 使用受限的 eval 环境
                eval(act, {'__builtins__': None}, ACTION_FUNCS)
            except Exception as e:
                self.get_logger().error(f'动作执行失败 {act}: {e}')

    def _call_vision_model(self, payload: dict) -> str:
        if not self.api_key:
            self.get_logger().error('ARK_API_KEY / DOUBAO_API_KEY 未设置，无法调用视觉大模型。')
            return ''

        request_data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            'https://ark.cn-beijing.volces.com/api/v3/responses',
            data=request_data,
            method='POST',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}',
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode('utf-8')
                data = json.loads(body)
                self.get_logger().info(f'模型原始返回: {data}')
                return self._extract_text_from_response(data)
        except urllib.error.HTTPError as e:
            self.get_logger().error(f'视觉模型HTTP错误: {e.code} {e.reason}')
            return ''
        except urllib.error.URLError as e:
            self.get_logger().error(f'视觉模型网络错误: {e.reason}')
            return ''
        except Exception as e:
            self.get_logger().error(f'视觉模型调用失败: {e}')
            return ''



    def _extract_text_from_response(self, data) -> str:
        if not isinstance(data, dict):
            return ''

        raw_text = ''

        if 'output' in data:
            output = data['output']
            if isinstance(output, str):
                raw_text = output.strip()
            elif isinstance(output, list) and output:
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

        import re  #使用正则表达式只保留中文字符和中文标点符号，过滤掉所有数字和其他无关字符
        # raw_text = re.sub(r'[^\u4e00-\u9fa5，。！？、；：\d℃%~]', '', raw_text)
        raw_text = re.sub(r'\s+', '', raw_text).strip()

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

    def _publish_description(self, text: str):
        self.get_logger().info(f'发布视觉回答: {text}')
        desc_msg = String()
        desc_msg.data = text
        self.description_publisher.publish(desc_msg)
        self.vision_answer_publisher.publish(desc_msg)
        
        self._synthesize_and_play(text)

    def _synthesize_and_play(self, text):
        """使用 edge-tts 语音合成并播放"""
        if not text.strip():
            self.get_logger().info("无文本需要合成")
            return
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            wav_data = loop.run_until_complete(self._edge_tts_synthesize(text))
            loop.close()
            
            if wav_data:
                cmd = ["aplay", "-D", self.audio_device, "-"]
                result = subprocess.run(cmd, input=wav_data)
                if result.returncode != 0:
                    self.get_logger().error(f"aplay 播放失败")
            else:
                self.get_logger().warning("音频数据为空")
                
        except Exception as e:
            self.get_logger().error(f"语音合成播放失败: {e}")
    
    async def _edge_tts_synthesize(self, text):
        communicate = edge_tts.Communicate(text, "zh-CN-XiaoyiNeural")
        mp3_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_data.extend(chunk["data"])
        
        result = subprocess.run(
            ["ffmpeg", "-i", "pipe:0", "-f", "wav", "-acodec", "pcm_s16le", "-ar", "24000", "pipe:1"],
            input=bytes(mp3_data),
            capture_output=True
        )
        if result.returncode != 0:
            self.get_logger().error(f"ffmpeg 转换失败: {result.stderr.decode()}")
            return b""
        return result.stdout

    def destroy_node(self):
        self.get_logger().info('正在关闭视觉节点和摄像头。')
        try:
            if self.cap is not None and self.cap.isOpened():
                self.cap.release()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = VisionChatNode()
    if not node.cap or not node.cap.isOpened():
        node.get_logger().fatal('摄像头初始化失败，节点将退出。')
        node.destroy_node()
        rclpy.shutdown()
        return

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('用户中断，节点关闭。')
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
