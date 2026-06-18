#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.task import Future
from rcl_interfaces.msg import SetParametersResult
from std_msgs.msg import String
import dashscope
from concurrent.futures import ThreadPoolExecutor
import subprocess
import os
import traceback

class TextToSpeechNode(Node):
    def __init__(self):
        super().__init__('text_to_speech_node')

        # --- TTS 配置 ---
        self.declare_parameter('dashscope_api_key', '')
        self.api_key = self.get_parameter('dashscope_api_key').get_parameter_value().string_value
        self.add_on_set_parameters_callback(self._parameters_callback)

        self._initialize_dashscope_client()

        self.tts_model = os.environ.get("DASHSCOPE_TTS_MODEL", "cosyvoice-v1") 
        self.voice = os.environ.get("DASHSCOPE_TTS_VOICE", "longcheng") 

        self.declare_parameter('audio_device', 'default')
        self.audio_device = self.get_parameter('audio_device').get_parameter_value().string_value

        self.aplay_format = "S24_LE" 
        self.aplay_rate = "48000"
        self.aplay_channels = "1"

        self.subscription = self.create_subscription(String, 'tts_input', self.text_callback, 10)
        self.state_publisher = self.create_publisher(String, 'speech_state', 10)
        self.web_display_publisher = self.create_publisher(String, '/web_display_text', 10)
        self.tts_executor = ThreadPoolExecutor(max_workers=1) 

        self.get_logger().info(f"文本转语音节点已启动 (Dashscope TTS: {self.tts_model}, 语音: {self.voice})。")
        self.get_logger().info(f"音频设备: {self.audio_device}, 播放格式: {self.aplay_format}@{self.aplay_rate}Hz, {self.aplay_channels}声道。")
        self.get_logger().info("等待 /tts_input 上的文本...")

    def _initialize_dashscope_client(self):
        if self.api_key:
            dashscope.api_key = self.api_key
            self.get_logger().info("Dashscope API 密钥已设置/更新。")
        else:
            self.get_logger().warn("Dashscope API 密钥为空，TTS 功能可能无法工作。")

    def _parameters_callback(self, params: list[Parameter]):
        for param in params:
            if param.name == 'dashscope_api_key':
                self.api_key = param.value
                self.get_logger().info(f"Dashscope API Key 已通过参数更新为: ...{self.api_key[-4:] if self.api_key else 'EMPTY'}")
                self._initialize_dashscope_client()
        return SetParametersResult(successful=True)
    
    def text_callback(self, msg):
        text = msg.data.strip()
        if not text:
            self.get_logger().info("收到空文本，跳过 TTS。")
            return
        
        if not self.api_key:
            self.get_logger().error("无法处理TTS请求：Dashscope API Key 未设置！")
            return

        self.get_logger().info(f"收到 TTS 文本: '{text}'")

        if self.web_display_publisher: 
            web_msg = String()
            web_msg.data = text
            self.web_display_publisher.publish(web_msg)

        state_msg_speaking = String()
        state_msg_speaking.data = "正在说话" 
        self.state_publisher.publish(state_msg_speaking)

        future = self.tts_executor.submit(self._synthesize_and_play_stream, text)
        future.add_done_callback(self._task_finished_callback)

    def _task_finished_callback(self, future: Future):
        try:
            future.result() 
            self.get_logger().info("Dashscope TTS 和播放任务成功完成。")
        except Exception as e:
            self.get_logger().error(f"Dashscope TTS 和播放任务出错: {type(e).__name__} - {e}\n{traceback.format_exc()}")
        finally:
            state_msg_listening = String()
            state_msg_listening.data = "正在聆听" 
            self.state_publisher.publish(state_msg_listening)
            self.get_logger().info("播放完成，状态已设置为“正在聆听”。")

    def _synthesize_segment(self, text_segment):
        if not text_segment.strip():
            return None
        self.get_logger().info(f"发送到 Dashscope 进行合成: '{text_segment[:50]}...'")
        try:
            synthesizer = dashscope.audio.tts_v2.SpeechSynthesizer(
                model=self.tts_model, voice=self.voice
            )
            audio_data_bytes = synthesizer.call(text_segment)
            if isinstance(audio_data_bytes, bytes) and audio_data_bytes:
                self.get_logger().info(f"Dashscope 合成 '{text_segment[:50]}...' ({len(audio_data_bytes)} 字节)")
                return audio_data_bytes
            else:
                self.get_logger().warn(f"Dashscope TTS 没有为以下文本返回音频数据: {text_segment[:50]}。响应类型: {type(audio_data_bytes)}")
                return None
        except Exception as e:
            self.get_logger().error(f"Dashscope TTS 合成错误，文本 '{text_segment[:50]}...': {type(e).__name__} - {e}\n{traceback.format_exc()}")
            return None

    def _standardize_audio_via_pipe(self, input_audio_data, segment_description="片段"): 
        if not input_audio_data:
            self.get_logger().warn(f"{segment_description}: 没有用于标准化的输入音频数据。")
            return None
        ffmpeg_cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
            "-acodec", "pcm_s24le", "-ar", self.aplay_rate, "-ac", self.aplay_channels,
            "-f", "wav", "pipe:1"
        ]
        self.get_logger().info(f"{segment_description}: 通过 ffmpeg 管道标准化音频...")
        try:
            process = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            standardized_wav_data, stderr_data = process.communicate(input=input_audio_data)
            if process.returncode != 0:
                self.get_logger().error(f"{segment_description}: ffmpeg 标准化失败。stderr: {stderr_data.decode('utf-8', errors='ignore')}")
                return None
            self.get_logger().info(f"{segment_description}: 音频标准化成功 ({len(standardized_wav_data)} 字节)。")
            return standardized_wav_data
        except FileNotFoundError:
            self.get_logger().error("未找到 ffmpeg 命令。请确保已安装 ffmpeg 并在 PATH 中。")
            return None
        except Exception as e:
            self.get_logger().error(f"{segment_description}: 管道音频标准化期间出错: {type(e).__name__} - {e}\n{traceback.format_exc()}")
            return None

    def _play_audio_via_pipe(self, audio_data, segment_description="片段"): 
        if not audio_data:
            self.get_logger().warn(f"{segment_description}: 没有要播放的音频数据。")
            return
        aplay_cmd = [
            "aplay", "-D", self.audio_device, "-q", "-f", self.aplay_format, 
            "-r", self.aplay_rate, "-c", self.aplay_channels
        ]
        self.get_logger().info(f"{segment_description}: 通过 aplay 管道播放音频 ({len(audio_data)} 字节)...")
        try:
            process = subprocess.Popen(aplay_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            _, stderr_data = process.communicate(input=audio_data) 
            if process.returncode != 0:
                self.get_logger().error(f"{segment_description}: aplay 播放失败。stderr: {stderr_data.decode('utf-8', errors='ignore')}")
        except FileNotFoundError:
            self.get_logger().error("未找到 aplay 命令。请确保已安装 alsa-utils (或等效工具) 并且 aplay 在 PATH 中。")
        except Exception as e:
            self.get_logger().error(f"{segment_description}: 管道音频播放期间出错: {type(e).__name__} - {e}\n{traceback.format_exc()}")

    def _synthesize_and_play_stream(self, text):
        if not text.strip():
            self.get_logger().info("没有要合成和播放的文本。")
            return
        self.get_logger().info(f"准备处理完整文本: '{text[:100]}...'")
        raw_audio_bytes = self._synthesize_segment(text)
        if not raw_audio_bytes:
            self.get_logger().warn(f"完整文本合成失败或未返回数据。")
            return
        standardized_audio_bytes = self._standardize_audio_via_pipe(raw_audio_bytes, "完整音频")
        if not standardized_audio_bytes:
            self.get_logger().warn(f"完整音频标准化失败。")
            return
        self._play_audio_via_pipe(standardized_audio_bytes, "完整音频")
        self.get_logger().info("已完成处理该语句的完整音频。")

    def destroy_node(self):
        self.get_logger().info("正在关闭文本转语音节点和线程池。")
        self.tts_executor.shutdown(wait=True) 
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    tts_node = TextToSpeechNode()
    try:
        rclpy.spin(tts_node)
    except KeyboardInterrupt:
        tts_node.get_logger().info("用户中断，正在关闭。")
    finally:
        tts_node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == '__main__':
    main()