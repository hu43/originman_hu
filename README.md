这是我的第一个开源作品

功能:
1. 多模态交互入口开发：支持用户通过命令行文本输入方式向机器人输入信息
2. 多模态输出能力实现：机器人需同步输出大模型处理结果对应的三种内容：语音播报内容、机器人实体动作指令、对应文本内容，保证输出的时序一致性与逻辑匹配性
3. 大模型视觉识别\图像与问题的结合\持续观察\生成描述性回答


非常感谢各位大佬提供的参考资料:
Originman程序分享链接：https://vscode.dev/github/xiaobairisk/originman/blob/main/originman_kick_ball
‌‬‬⁠⁠⁠‬‍子豪兄TonyPi机器人交付 - 飞书云文档：https://my.feishu.cn/docx/Z0dkdyNpTojSXWx06zZcjTjXndg
Originman使用教程：https://originman.guyuehome.com/zh/guide/quick_guide/#1


使用方法：
1、项目放如图目录所示<img width="357" height="816" alt="image" src="https://github.com/user-attachments/assets/9090d9b1-6e2e-436e-a13a-55fe0013d1b4" />

2、在orginman_hu/integrated_chat_node.py内将api_key改为自己的deepseek的key

3、继续在该文件内将以下语音程序配置改为自己机器人的音频配置  
        # 本地语音合成配置
        self.audio_device = "plughw:0,0"
        
4、用ssh将自己的机器人连接到自己范围内的wifi
sudo nmcli device wifi list          # 列出找到的wifi网络
sudo wifi_connect "WiFi用户名" "WiFi密码"   # Linux连wifi

5、
## 安装工具包
```shell
pip install opencv-python jupyter notebook openai appbuilder-sdk qianfan cozepy boto3 anthropic
```

6、打开VLA文件夹后,分别运行integrated_chat_node.py(大模型与人机动作整合);vision_chat_node.py(大模型与机器人摄像头整合),最后命令行输入你要跟机器人交流的内容

7、有问题问AI,有问题问AI,有问题问AI!!我的也是ai帮我写好的


ai提示词内容:
1,<img width="268" height="352" alt="image" src="https://github.com/user-attachments/assets/94dcd202-56cd-4e27-8bdf-f33a605cd4bd" />
2,参考orginman_hu文件夹内的originman_vision和integrated_chat_node内的代码，另起一份新的python运行文件，要实现摄像头与大模型的功能整合。功能要求实现大模型视觉识别：视觉理解：机器人不仅仅是一个执行者，它还拥有一双“眼睛”，能够观察和理解周围的世界。
实现方式：
持续观察: 机器人通过摄像头以固定频率捕捉图像，并将其发布到 ROS 网络中，为系统提供实时的视觉输入。
图像与问题的结合: 当您提出一个关于视觉的问题，例如“你看到了什么？”，机器人会获取最新的摄像头图像，并将其与您的问题文本一起发送给多模态大模型。
生成描述性回答: 大模型能够理解图像内容和文本问题的关联，并生成一段详细的、人性化的描述性文字作为回答，例如“我看到了桌子上有一个红色的苹果...”等。

所有任务行为只能在orginman_hu内进行，不能处理这个文件夹外的文件，并且要保证原orginman_hu内的所有功能能正常运行。

大模型使用doubao-seed-2.0-pro对应的配置如下：
curl https://ark.cn-beijing.volces.com/api/v3/responses \
-H "Authorization: Bearer $UAPI" \
-H 'Content-Type: application/json' \
-d '{
    "model": "doubao-seed-2-0-pro-260215",
    "input": [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/ark_demo_img_1.png"
                },
                {
                    "type": "input_text",
                    "text": "你看见了什么？"
                }
            ]
        }
    ]
}'




联系方式:2533764649@qq.com
