这是我的第一个开源作品（PS：来自一个不会手搓代码的新时代AI程序工程师。。）
 （用它——》VLA/vision_integrated_chat_node.py）
功能:

多模态交互入口开发：支持用户通过命令行文本输入方式向机器人输入信息
多模态输出能力实现：机器人需同步输出大模型处理结果对应的三种内容：语音播报内容、机器人实体动作指令、对应文本内容，保证输出的时序一致性与逻辑匹配性
大模型视觉识别\图像与问题的结合\持续观察\生成描述性回答
成功实现oringinman内的大模型、摄像头、动作及联网四者功能整合，并深度思考与输出内容无冲突。（成功实现超低配版vla）
制作了一个独立的网页控制服务，用户可以在浏览器中打开页面后，通过按钮直接发送基础动作指令给机器人。

非常感谢各位大佬提供的参考资料: Originman程序分享链接：https://vscode.dev/github/xiaobairisk/originman/blob/main/originman_kick_ball ‌‬‬⁠⁠⁠‬‍子豪兄TonyPi机器人交付 - 飞书云文档：https://my.feishu.cn/docx/Z0dkdyNpTojSXWx06zZcjTjXndg Originman使用教程：https://originman.guyuehome.com/zh/guide/quick_guide/#1

使用方法： 1、项目放如图目录所示image

2、在orginman_hu/integrated_chat_node.py内将api_key改为自己的deepseek的key

3、继续在该文件内将以下语音程序配置改为自己机器人的音频配置
# 本地语音合成配置 self.audio_device = "plughw:0,0"

4、用ssh将自己的机器人连接到自己范围内的wifi sudo nmcli device wifi list # 列出找到的wifi网络 sudo wifi_connect "WiFi用户名" "WiFi密码" # Linux连wifi

5、

安装工具包
pip install opencv-python jupyter notebook openai appbuilder-sdk qianfan cozepy boto3 anthropic
6、打开VLA文件夹后,分别运行integrated_chat_node.py(大模型与人机动作整合);vision_chat_node.py(大模型与机器人摄像头整合),最后命令行输入你要跟机器人交流的内容

7、有问题问AI,有问题问AI,有问题问AI!!我的也是ai帮我写好的

ai提示词内容: 1,image 2,参考orginman_hu文件夹内的originman_vision和integrated_chat_node内的代码，另起一份新的python运行文件，要实现摄像头与大模型的功能整合。功能要求实现大模型视觉识别：视觉理解：机器人不仅仅是一个执行者，它还拥有一双“眼睛”，能够观察和理解周围的世界。 实现方式： 持续观察: 机器人通过摄像头以固定频率捕捉图像，并将其发布到 ROS 网络中，为系统提供实时的视觉输入。 图像与问题的结合: 当您提出一个关于视觉的问题，例如“你看到了什么？”，机器人会获取最新的摄像头图像，并将其与您的问题文本一起发送给多模态大模型。 生成描述性回答: 大模型能够理解图像内容和文本问题的关联，并生成一段详细的、人性化的描述性文字作为回答，例如“我看到了桌子上有一个红色的苹果...”等。
3，在/userdata/dev_ws/src/originman/originman_hu/web文件夹内另起一份新的python运行文件，帮我实现用网页控制机器人的程序，要求：用户可以打开浏览器，在页面中输入对应网址后，通过点击网址内的对应动作按钮，实现对机器人基础动作功能的控制。

所有任务行为只能在originman_hu/web文件夹内进行，不能处理这个文件夹外的文件，并且要保证原originman_hu内的所有功能能正常运行。


所有任务行为只能在orginman_hu内进行，不能处理这个文件夹外的文件，并且要保证原orginman_hu内的所有功能能正常运行。

大模型使用doubao-seed-2.0-pro对应的配置如下： curl https://ark.cn-beijing.volces.com/api/v3/responses
-H "Authorization: Bearer $UAPI"
-H 'Content-Type: application/json'
-d '{ "model": "doubao-seed-2-0-pro-260215", "input": [ { "role": "user", "content": [ { "type": "input_image", "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/ark_demo_img_1.png" }, { "type": "input_text", "text": "你看见了什么？" } ] } ] }'






联系方式:2533764649@qq.com






（以下为ai生成）
OriginMan 网页控制器
这个目录下提供了一个独立的网页控制服务，用户可以在浏览器中打开页面后，通过按钮直接发送基础动作指令给机器人。

功能说明
打开网页后，可以直接点击动作按钮控制机器人基础动作
支持的动作包括：站立、前进、后退、左移、右移、左转、右转、挥手、鞠躬、下蹲、踢右脚、踢左脚、仰卧起坐、踏步、前趴起立、后躺起立
服务会通过 ROS 2 话题发送动作命令
启动方式
在当前目录下执行：

./start_web_controller.sh
如果需要指定监听地址或端口，可以直接运行：

python3 web_robot_controller.py --host 0.0.0.0 --port 8000
使用步骤
确认 ROS 2 环境已经可用，且机器人相关动作节点正在运行
在终端中进入当前目录
执行 ./start_web_controller.sh
浏览器中打开：
http://127.0.0.1:8000/
或者 http://本机IP:8000/
点击页面中的按钮即可发送动作
接口说明
页面首页：/
健康检查：/health
发送动作：POST /action
说明
本方案只在当前目录内新增了网页控制相关文件，不修改原有的 OriginMan 功能
如需修改动作映射，请编辑 web_robot_controller.py 中的 _normalize_action 方法












