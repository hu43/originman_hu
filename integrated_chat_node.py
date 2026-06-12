#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from openai import OpenAI
import os
import logging
import json
import threading
import time
import hiwonder.ActionGroupControl as AGC
import subprocess
import asyncio
import edge_tts

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 提示词模板
robot_order_template = '''
你是我的机器人，请你根据我的指令，以json形式输出接下来要运行的对应函数和你给我的回复
你只需要回答一个列表即可，不要回答任何中文
【以下是所有动作函数】
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
从前倾趴卧起立，也就是从趴下到站起来：stand_up_front()
从后仰躺倒起立，也就是从躺下到站起来：stand_up_back()
巡线跨栏模式，顺着黑色线前进并跨越台阶等障碍物：athletics()
播放音乐并跳舞（唱跳RAP）：twist()
踢不同颜色的足球：kickball('red')
搬运不同颜色的海绵方块：transport('red green blue')

【输出限制】
你直接输出json即可，从{开始，以}结束，【不要】输出```json的开头或结尾
在'action'键中，输出函数名列表，列表中每个元素都是字符串，代表要运行的函数名称和参数。每个函数既可以单独运行，也可以和其他函数先后运行。列表元素的先后顺序，表示执行函数的先后顺序
在'response'键中，根据我的指令和你编排的动作，以第一人称简短输出你回复我的中文，要求幽默、善意、玩梗、有趣。不要超过20个字，不要回复英文。
如果我让你从躺倒状态站起来，你回复一些和“躺平”相关的话
kickball和transport函数需要用双引号

【以下是一些具体的例子】
我的指令：你最喜欢哪种颜色呀。你回复：{'action':[], 'response':'我喜欢蓝色，因为我喜欢贝加尔湖，深邃而神秘'}
我的指令：请你先鞠个躬，然后挥挥手。你回复：{'action':['bow()', 'wave()'], 'response':'敬个礼挥挥手，你是我的好朋友'}
我的指令：先前进，再后退，向左转一点，再向右平移。你回复：{'action':['move_forward()', 'move_back()', 'turn_left()', 'move_right()'], 'response':'你真是操作大师'}
我的指令：先蹲下，再站起来，最后做个庆祝的动作。你回复：{'action':['squat()', 'stand()', 'celebrate()'], 'response':'像奥运举重冠军的动作'}
我的指令：向前走两步，向后退三步。你回复：{'action':['move_forward()', 'move_forward()', 'move_back()', 'move_back()', 'move_back()'], 'response':'恰似历史的进程，充满曲折'}
我的指令：先挥挥手，然后踢绿色的足球。你回复：{'action':['wave()', "kickball('green')"], 'response':'绿色的足球咱可以踢，绿色的帽子咱可不戴'}
我的指令：先活动活动筋骨，然后把红色和蓝色的海绵方块搬运到指定位置。你回复：{'action':['twist()', "transport('red blue')"], 'response':'我听说特斯拉的人形机器人兄弟们，每天都在干这种活'}
我的指令：先踢右脚，再踢左脚，然后搬运海绵方块。你回复：{'action':['right_shot()', 'left_shot()', "transport('red green blue')"], 'response':'让我先活动活动，然后让海绵宝宝们各回各家'}
我的指令：别躺着了，快起来，把红色 and 蓝色方块搬运到指定位置。你回复：{'action':['stand_up_back()', "transport('red blue')"], 'response':'我也想躺平啊，奈何得干活儿'}

【我现在的指令是】
'''

# 动作执行函数封装
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
def athletics(): os.system('python3 /userdata/dev_ws/src/originman/orginman_hu/TonyPi-API-20241116_no_key/TonyPi/备份代码/athletics_perform_only.py')
def kickball(color='red'): os.system(f'python3 /userdata/dev_ws/src/originman/orginman_hu/TonyPi-API-20241116_no_key/TonyPi/备份代码/KickBall_only_once.py {color}')
def transport(color_list_str='red green blue'):
    color_list = color_list_str.split(' ')
    os.system(f'python3 /userdata/dev_ws/src/originman/orginman_hu/TonyPi-API-20241116_no_key/TonyPi/备份代码/Transport_only.py "{color_list}"')

class IntegratedChatNode(Node):
    def __init__(self):
        super().__init__('integrated_chat_node')
        
        # DeepSeek 配置
        self.api_key = "sk-be5df3a1dc7c4e6787ed02a92a805984"
        self.base_url = "https://api.deepseek.com/v1"
        self.model = "deepseek-chat"
        
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        
        # 本地语音合成配置
        self.audio_device = "plughw:0,0"
        
        # 话题订阅（仅用于语音输入）
        self.text_input_subscription = self.create_subscription(
            String,
            'text_input',
            self.text_callback,
            10
        )
        
        self.get_logger().info("集成交互节点已启动，等待语音或命令行输入...")
        
        # 启动 CLI 输入线程
        self.cli_thread = threading.Thread(target=self.cli_input_loop, daemon=True)
        self.cli_thread.start()

    def cli_input_loop(self):
        """命令行输入循环"""
        while rclpy.ok():
            try:
                user_input = input("\n[CLI Input]: ").strip()
                if user_input:
                    if user_input.lower() in ['exit', 'quit']:
                        self.get_logger().info("退出程序...")
                        rclpy.shutdown()
                        break
                    self.process_query(user_input)
            except EOFError:
                break
            except Exception as e:
                self.get_logger().error(f"CLI 输入异常: {e}")

    def text_callback(self, msg):
        """语音识别文本回调"""
        text = msg.data.strip()
        if text:
            self.get_logger().info(f"收到语音输入: {text}")
            self.process_query(text)

    def process_query(self, text):
        """处理用户查询：大模型推理 -> 同步输出"""
        self.get_logger().info(f"正在向 DeepSeek 请求: {text}")
        
        # 构造 Prompt
        prompt = robot_order_template + text
        
        try:
            # 调用 DeepSeek
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False
            )
            
            response_content = completion.choices[0].message.content.strip()
            self.get_logger().info(f"LLM 原始响应: {response_content}")
            
            # 解析响应内容 (兼容单引号或被 ```json 包裹的情况)
            try:
                # 清洗响应
                clean_content = response_content
                if clean_content.startswith("```json"):
                    clean_content = clean_content[7:-3].strip()
                elif clean_content.startswith("```"):
                    clean_content = clean_content[3:-3].strip()
                
                # 尝试用 ast.literal_eval 处理可能的单引号 JSON
                import ast
                try:
                    data = json.loads(clean_content)
                except json.JSONDecodeError:
                    data = ast.literal_eval(clean_content)
                
                # 如果返回的是列表，取第一个
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                
                actions = data.get('action', [])
                response_text = data.get('response', '')
                
                # 1. 文本输出
                print(f"\n[Robot Response]: {response_text}")
                if actions:
                    print(f"[Robot Actions]: {actions}")
                
                # 2. 语音输出 (使用 eSpeak 本地合成并播放)
                if response_text:
                    self.get_logger().info(f"开始语音合成: {response_text}")
                    self._synthesize_and_play(response_text)
                
                # 3. 动作执行
                for action_str in actions:
                    try:
                        self.get_logger().info(f"执行动作: {action_str}")
                        # 使用 eval 在受限作用域内执行动作函数
                        eval(action_str, {"__builtins__": None}, {
                            "stand": stand,
                            "move_forward": move_forward,
                            "move_back": move_back,
                            "move_left": move_left,
                            "move_right": move_right,
                            "turn_left": turn_left,
                            "turn_right": turn_right,
                            "bow": bow,
                            "wave": wave,
                            "twist": twist,
                            "celebrate": celebrate,
                            "squat": squat,
                            "right_shot": right_shot,
                            "left_shot": left_shot,
                            "sit_ups": sit_ups,
                            "stepping": stepping,
                            "wing_chun": wing_chun,
                            "stand_up_front": stand_up_front,
                            "stand_up_back": stand_up_back,
                            "athletics": athletics,
                            "kickball": kickball,
                            "transport": transport
                        })
                    except Exception as e:
                        self.get_logger().error(f"动作 {action_str} 执行失败: {e}")
                
            except Exception as e:
                self.get_logger().error(f"解析 LLM 响应失败: {e}")
                print(f"\n[Robot Response (Raw)]: {response_content}")
                
        except Exception as e:
            self.get_logger().error(f"调用 DeepSeek API 失败: {e}")

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
        communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
        mp3_data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_data.extend(chunk["data"])
        
        # 使用 ffmpeg 将 MP3 转换为 WAV
        result = subprocess.run(
            ["ffmpeg", "-i", "pipe:0", "-f", "wav", "-acodec", "pcm_s16le", "-ar", "24000", "pipe:1"],
            input=bytes(mp3_data),
            capture_output=True
        )
        if result.returncode != 0:
            self.get_logger().error(f"ffmpeg 转换失败: {result.stderr.decode()}")
            return b""
        return result.stdout

def main(args=None):
    rclpy.init(args=args)
    node = IntegratedChatNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
