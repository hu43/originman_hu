# aliyun_qwen_ros/launch/robot_interaction.launch.py
from launch import LaunchDescription
from launch_ros.actions import Node
import os

def generate_launch_description():
    # 你的功能包名称，请确保与实际一致
    your_pkg_name = 'originman_vision' 

    # --- 现有节点定义 (保持不变) ---

    web_interface_node = Node(
        package=your_pkg_name,
        executable='web_interface_node',
        name='web_interface_node',
        output='screen'
    )

    originman_action_node = Node(
        package=your_pkg_name,
        executable='originman_action_node',
        name='originman_action_node',
        output='screen'
    )

    image_publisher_node = Node(
        package=your_pkg_name,
        executable='image_publisher_node',
        name='image_publisher_node',
        output='screen',
        parameters=[
            {'camera_index': 0},
            {'publish_frequency': 2.0}
        ]
    )

    image_caption_node = Node(
        package=your_pkg_name,
        executable='image_caption_node',
        name='image_caption_node',
        output='screen',
        parameters=[{
            'dashscope_api_key': os.environ.get('DASHSCOpe_API_KEY', '')
        }]
    )

    text_to_speech_node = Node(
        package=your_pkg_name,
        executable='text_to_speech_node',
        name='text_to_speech_node',
        output='screen',
        parameters=[
            {'audio_device': 'default'},
            {'dashscope_api_key': os.environ.get('DASHSCOPE_API_KEY', '')}
        ]
    )
    
    rosbridge_server_node = Node(
        package='rosbridge_server',
        executable='rosbridge_websocket',
        name='rosbridge_websocket',
        parameters=[{'port': 9090}]
    )

    # --- 配置 voice_control_node ---
    voice_control_node = Node(
        package=your_pkg_name,
        executable='voice_control_node',
        name='voice_control_node',
        output='screen',
        parameters=[
            {
                'dashscope_api_key': os.environ.get('DASHSCOPE_API_KEY', ''),
                'hardware_sample_rate': 48000,
                'asr_sample_rate': 16000,
                'model': 'paraformer-realtime-v2',
                'input_device_name': 'default', 
                'vad_aggressiveness': 1,
                'silence_duration_s': 1.2
            }
        ]
    )

    return LaunchDescription([
        web_interface_node,
        originman_action_node,
        image_publisher_node,
        image_caption_node,
        text_to_speech_node,
        rosbridge_server_node,
        voice_control_node 
    ])