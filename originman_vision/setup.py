from setuptools import find_packages, setup
import os
from glob import glob # 用来匹配文件路径模式

package_name = 'originman_vision'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob(os.path.join('launch', '*.launch.py'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='root',
    maintainer_email='root@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'web_interface_node = originman_vision.web_interface_node:main',
            'originman_action_node = originman_vision.originman_action_node:main',
            'image_caption_node = originman_vision.image_caption_node:main',
            'image_publisher_node = originman_vision.image_publisher_node:main',
            'text_to_speech_node = originman_vision.text_to_speech_node:main',
            'voice_control_node = originman_vision.voice_control_node:main',
        ],
    },
)
