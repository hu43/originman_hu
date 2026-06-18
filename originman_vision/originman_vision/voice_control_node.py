#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rcl_interfaces.msg import SetParametersResult
from std_msgs.msg import String
import dashscope
from http import HTTPStatus
import numpy as np
import pyaudio
import threading
import os
import wave
import subprocess
import traceback
import time

class VoiceControlNode(Node):
    def __init__(self):
        super().__init__('voice_control_node')

        # --- Parameters ---
        self.declare_parameter('dashscope_api_key', '')
        self.declare_parameter('model', 'paraformer-realtime-v2')
        self.declare_parameter('input_device_name', 'default')
        self.declare_parameter('hardware_sample_rate', 48000)
        self.declare_parameter('asr_sample_rate', 16000)
        self.declare_parameter('audio_channels', 1)
        self.declare_parameter('min_speech_duration_s', 0.3)
        self.declare_parameter('temp_audio_path', '/tmp/ros_asr_temp.wav')
        
        # --- Get Parameters ---
        self.api_key = self.get_parameter('dashscope_api_key').get_parameter_value().string_value
        self.model = self.get_parameter('model').get_parameter_value().string_value
        self.device_name = self.get_parameter('input_device_name').get_parameter_value().string_value
        self.hardware_rate = self.get_parameter('hardware_sample_rate').get_parameter_value().integer_value
        self.asr_rate = self.get_parameter('asr_sample_rate').get_parameter_value().integer_value
        self.channels = self.get_parameter('audio_channels').get_parameter_value().integer_value
        self.min_speech_duration_s = self.get_parameter('min_speech_duration_s').get_parameter_value().double_value
        self.temp_audio_path = self.get_parameter('temp_audio_path').get_parameter_value().string_value

        self.add_on_set_parameters_callback(self._parameters_callback)
        self._initialize_dashscope_client()
        
        # --- ROS Interfaces ---
        self.text_publisher = self.create_publisher(String, 'recognized_text', 10)
        self.state_publisher = self.create_publisher(String, 'speech_state', 10)
        self.speech_state_subscription = self.create_subscription(String, 'speech_state', self.speech_state_callback, 10)
        self.control_subscription = self.create_subscription(String, '/voice_control_command', self.control_callback, 10)
        
        self.is_robot_speaking = False
        
        # --- Audio & State Management ---
        self.p_audio = pyaudio.PyAudio()
        self.audio_stream = None
        self.is_recording = False
        self.recorded_frames = []
        self.recording_lock = threading.Lock()
        self.stream_reset_event = threading.Event()
        
        self.is_running = True
        self.audio_thread = threading.Thread(target=self.audio_stream_loop)
        self.audio_thread.start()
        
        self.get_logger().info("语音控制节点已启动，等待手动控制指令...")
        self.get_logger().info(f"麦克风: {self.device_name} @ {self.hardware_rate}Hz")

    def _initialize_dashscope_client(self):
        if self.api_key:
            dashscope.api_key = self.api_key
            self.get_logger().info("Dashscope API 密钥已设置/更新。")
        else:
            self.get_logger().warn("Dashscope API 密钥为空，语音识别功能可能无法工作。")

    def _parameters_callback(self, params: list[Parameter]):
        for param in params:
            if param.name == 'dashscope_api_key':
                self.api_key = param.value
                self.get_logger().info(f"Dashscope API Key 已通过参数更新为: ...{self.api_key[-4:] if self.api_key else 'EMPTY'}")
                self._initialize_dashscope_client()
        return SetParametersResult(successful=True)
        
    def speech_state_callback(self, msg):
        was_speaking = self.is_robot_speaking
        self.is_robot_speaking = (msg.data == "正在说话")

        if self.is_robot_speaking and self.is_recording:
            self.get_logger().warn("机器人开始说话，强制停止录音。")
            self.stop_recording()
        
        if was_speaking and not self.is_robot_speaking:
            self.get_logger().info("检测到机器人已停止说话，将重置音频流以确保麦克风可用。")
            self.stream_reset_event.set()

    def control_callback(self, msg):
        command = msg.data.upper()
        if command == "START":
            self.start_recording()
        elif command == "STOP":
            self.stop_recording()

    def start_recording(self):
        with self.recording_lock:
            if self.is_recording:
                self.get_logger().warn("已在录音中，忽略 'START' 指令。")
                return
            if self.is_robot_speaking:
                self.get_logger().warn("机器人正在说话，无法开始录音。")
                return
            self.is_recording = True
            self.recorded_frames = []
            self.state_publisher.publish(String(data="正在聆听"))
            self.get_logger().info("收到指令，开始录音...")

    def stop_recording(self):
        frames_to_process = None
        with self.recording_lock:
            if not self.is_recording:
                return 
            self.is_recording = False
            frames_to_process = self.recorded_frames
            self.recorded_frames = [] 
            self.get_logger().info("收到指令，停止录音。")
        if frames_to_process:
            processing_thread = threading.Thread(
                target=self.process_and_recognize, 
                args=(frames_to_process,)
            )
            processing_thread.start()
        else:
            self.get_logger().info("录音内容为空，不进行识别。")

    def find_device_index(self):
        try:
            # If the user provides a specific name (not 'default'), try to find it
            if self.device_name != 'default':
                for i in range(self.p_audio.get_device_count()):
                    dev_info = self.p_audio.get_device_info_by_index(i)
                    if self.device_name in dev_info.get("name", ""):
                        self.get_logger().info(f"找到指定麦克风: {dev_info['name']}")
                        return i
                self.get_logger().warn(f"未找到指定麦克风 '{self.device_name}', 将使用默认设备。")
            
            # For 'default' or if the search fails, get the default device info
            default_device_info = self.p_audio.get_default_input_device_info()
            self.get_logger().info(f"使用系统默认麦克风: {default_device_info['name']}")
            return default_device_info['index']

        except Exception as e:
            self.get_logger().error(f"查找麦克风时出错: {e}. 将尝试使用索引0。")
            return 0


    def open_new_stream(self):
        try:
            device_index = self.find_device_index()
            chunk_size = int(self.hardware_rate * 30 / 1000)
            self.audio_stream = self.p_audio.open(
                format=pyaudio.paInt16, channels=self.channels, rate=self.hardware_rate,
                input=True, input_device_index=device_index, frames_per_buffer=chunk_size,
            )
            self.get_logger().info("麦克风音频流已成功打开/重置。")
            return chunk_size
        except Exception as e:
            self.get_logger().fatal(f"打开/重置麦克风失败: {e}")
            self.is_running = False
            return None

    def audio_stream_loop(self):
        chunk_size = self.open_new_stream()
        if chunk_size is None:
            return
        while self.is_running and rclpy.ok():
            if self.stream_reset_event.is_set():
                self.get_logger().info("正在执行音频流重置...")
                if self.audio_stream.is_active():
                    self.audio_stream.stop_stream()
                self.audio_stream.close()
                time.sleep(0.1) 
                chunk_size = self.open_new_stream()
                if chunk_size is None:
                    break
                self.stream_reset_event.clear()
            try:
                audio_chunk = self.audio_stream.read(chunk_size, exception_on_overflow=False)
                with self.recording_lock:
                    if self.is_recording:
                        self.recorded_frames.append(audio_chunk)
            except IOError as e:
                if e.errno == pyaudio.paBadStreamPtr:
                    self.get_logger().warn("音频流指针无效 (可能正在重置)，短暂等待...")
                    time.sleep(0.1)
                else:
                    self.get_logger().warn(f"读取音频流时出错: {e}")
            except Exception as e:
                self.get_logger().error(f"音频流线程发生未知错误: {e}")
                self.is_running = False

    def process_and_recognize(self, frames):
        if not self.api_key:
            self.get_logger().error("无法进行语音识别：Dashscope API Key 未设置！")
            return
            
        total_bytes = sum(len(f) for f in frames)
        duration = total_bytes / (self.hardware_rate * 2.0)

        if duration < self.min_speech_duration_s:
            self.get_logger().info(f"录音时长 ({duration:.2f}s) 过短，已忽略。")
            return
        
        self.get_logger().info(f"正在处理 {duration:.2f} 秒的音频...")
        self.state_publisher.publish(String(data="正在识别"))
        
        final_audio_path = self.temp_audio_path 
        temp_high_rate_path = "/tmp/ros_asr_temp_48k.wav"

        try:
            with wave.open(temp_high_rate_path, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2)
                wf.setframerate(self.hardware_rate)
                wf.writeframes(b''.join(frames))
            
            ffmpeg_command = [
                'ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', temp_high_rate_path,
                '-ar', str(self.asr_rate), '-ac', str(self.channels), '-y', final_audio_path
            ]
            subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True)
            self.get_logger().info(f"重采样成功，文件已保存: {final_audio_path}")

            recognizer = dashscope.audio.asr.Recognition(
                model=self.model, format='wav', sample_rate=self.asr_rate, callback=None
            )
            response = recognizer.call(file=final_audio_path)

            if response is None:
                self.get_logger().error("API调用返回了空结果(None)！")
                return

            if response.status_code == HTTPStatus.OK:
                output = response.get('output', {})
                if output and 'sentence' in output and output['sentence']:
                    recognized_text = ''.join([s.get('text', '') for s in output['sentence']])
                    if recognized_text:
                        self.get_logger().info(f"语音识别成功: '{recognized_text}'")
                        self.text_publisher.publish(String(data=recognized_text))
                    else:
                        self.get_logger().warn("API调用成功，但解析出的文本为空。")
                else:
                    self.get_logger().warn("API调用成功，但返回的output为空或不包含'sentence'。")
            else:
                self.get_logger().error(f"语音识别API调用失败。状态码: {response.status_code}, 消息: {response.message}")
        
        except subprocess.CalledProcessError as e:
            self.get_logger().error(f"ffmpeg 重采样失败: {e.stderr}")
        except Exception as e:
            self.get_logger().error(f"语音识别处理流程中发生未知错误: {e}\n{traceback.format_exc()}")
        finally:
            if os.path.exists(final_audio_path): os.remove(final_audio_path)
            if os.path.exists(temp_high_rate_path): os.remove(temp_high_rate_path)

    def destroy_node(self):
        self.get_logger().info("正在关闭语音控制节点...")
        self.is_running = False
        if hasattr(self, 'audio_thread') and self.audio_thread.is_alive():
            self.audio_thread.join()
        if hasattr(self, 'audio_stream') and self.audio_stream:
            if self.audio_stream.is_active():
                self.audio_stream.stop_stream()
            self.audio_stream.close()
        if hasattr(self, 'p_audio'):
            self.p_audio.terminate()
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = VoiceControlNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == '__main__':
    main()