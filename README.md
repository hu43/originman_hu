这是我的第一个开源作品

功能:
1. 多模态交互入口开发：支持用户通过命令行文本输入方式向机器人输入信息
2. 多模态输出能力实现：机器人需同步输出大模型处理结果对应的三种内容：语音播报内容、机器人实体动作指令、对应文本内容，保证输出的时序一致性与逻辑匹配性

非常感谢各位大佬提供的参考资料:
Originman程序分享链接：https://vscode.dev/github/xiaobairisk/originman/blob/main/originman_kick_ball
‌‬‬⁠⁠⁠‬‍子豪兄TonyPi机器人交付 - 飞书云文档：https://my.feishu.cn/docx/Z0dkdyNpTojSXWx06zZcjTjXndg
Originman使用教程：https://originman.guyuehome.com/zh/guide/quick_guide/#1


使用方法：
1、在orginman_hu/integrated_chat_node.py内将api_key改为自己的deepseek的key

2、继续在该文件内将以下语音程序配置改为自己机器人的音频配置  
        # 本地语音合成配置
        self.audio_device = "plughw:0,0"
        
3、用ssh将自己的机器人连接到自己范围内的wifi
sudo nmcli device wifi list          # 列出找到的wifi网络
sudo wifi_connect "WiFi用户名" "WiFi密码"   # Linux连wifi

4、
## 安装工具包
```shell
pip install opencv-python jupyter notebook openai appbuilder-sdk qianfan cozepy boto3 anthropic
```

5、直接运行integrated_chat_node.py,然后在命令行输入你要跟机器人交流的内容

6、有问题问AI,有问题问AI,有问题问AI!!我的也是ai帮我写好的


ai提示词内容:
<img width="268" height="352" alt="image" src="https://github.com/user-attachments/assets/94dcd202-56cd-4e27-8bdf-f33a605cd4bd" />




联系方式:2533764649@qq.com
