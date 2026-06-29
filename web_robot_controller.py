#!/usr/bin/env python3
import argparse
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict

import hiwonder.ActionGroupControl
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class RobotActionPublisher:
    def __init__(self) -> None:
        self.node: Node | None = None
        self.publisher = None
        self._lock = threading.Lock()
        self._ready = False

    def init_ros(self) -> bool:
        with self._lock:
            if self._ready:
                return True
            try:
                if not rclpy.ok():
                    rclpy.init(args=None)
                self.node = rclpy.create_node("originman_web_controller")
                self.publisher = self.node.create_publisher(String, "/robot_action_command", 10)
                self._ready = True
                return True
            except Exception as exc:
                print(f"ROS2 初始化失败: {exc}")
                return False

    def publish_action(self, action_name: str) -> bool:
        action_name = (action_name or "").strip()
        if not action_name:
            return False

        if self.init_ros():
            try:
                msg = String()
                msg.data = json.dumps({"action_name": action_name, "repetitions": 1})
                self.publisher.publish(msg)
                subscription_count = getattr(self.publisher, "get_subscription_count", lambda: 0)()
                if subscription_count > 0:
                    return True
                print("ROS2 话题当前没有订阅者，改为直接执行本地动作。")
            except Exception as exc:
                print(f"发布动作失败: {exc}")

        return self._run_local_action(action_name)

    def _run_local_action(self, action_name: str) -> bool:
        try:
            hiwonder.ActionGroupControl.runActionGroup(action_name)
            return True
        except Exception as exc:
            print(f"本地执行动作失败: {exc}")
            return False

    def shutdown(self) -> None:
        if self.node is not None:
            try:
                self.node.destroy_node()
            except Exception:
                pass
        if rclpy.ok():
            rclpy.shutdown()


class RobotWebHandler(BaseHTTPRequestHandler):
    server_version = "OriginManWebController/1.0"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._serve_file("index.html", "text/html; charset=utf-8")
            return
        if path == "/health":
            self._send_json({"status": "ok"})
            return
        self._send_text("Not Found", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/action":
            self._send_text("Not Found", HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body or "{}")
        except Exception:
            self._send_json({"ok": False, "message": "请求体不是有效的 JSON"}, HTTPStatus.BAD_REQUEST)
            return

        action_name = (payload.get("action") or payload.get("action_name") or "").strip()
        if not action_name:
            self._send_json({"ok": False, "message": "缺少动作名称"}, HTTPStatus.BAD_REQUEST)
            return

        action_name = self._normalize_action(action_name)
        if not action_name:
            self._send_json({"ok": False, "message": "不支持的动作"}, HTTPStatus.BAD_REQUEST)
            return

        success = self.server.robot_publisher.publish_action(action_name)
        if success:
            self._send_json({"ok": True, "action": action_name, "message": f"动作已发送: {action_name}"})
        else:
            self._send_json({"ok": False, "message": "动作发送失败，请确认 ROS2 环境已启动且动作节点正在运行"}, HTTPStatus.SERVICE_UNAVAILABLE)

    def log_message(self, format: str, *args) -> None:
        print(f"[web] {self.address_string()} - {format % args}")

    def _normalize_action(self, action_name: str) -> str:
        mapping: Dict[str, str] = {
            "stand": "stand",
            "forward": "go_forward",
            "back": "back_fast",
            "left": "left_move_fast",
            "right": "right_move_fast",
            "turn_left": "turn_left",
            "turn_right": "turn_right",
            "wave": "wave",
            "bow": "bow",
            "squat": "squat",
            "kick_right": "right_shot_fast",
            "kick_left": "left_shot_fast",
            "sit_ups": "sit_ups",
            "stepping": "stepping",
            "stand_up_front": "stand_up_front",
            "stand_up_back": "stand_up_back",
        }
        normalized = action_name.lower().strip()
        return mapping.get(normalized, "")

    def _serve_file(self, filename: str, content_type: str) -> None:
        file_path = Path(__file__).resolve().parent / filename
        if not file_path.exists():
            self._send_text("File Not Found", HTTPStatus.NOT_FOUND)
            return
        try:
            content = file_path.read_bytes()
        except Exception as exc:
            self._send_text(f"Read file error: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload: Dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class RobotHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_cls, robot_publisher: RobotActionPublisher):
        self.allow_reuse_address = True
        super().__init__(server_address, handler_cls)
        self.robot_publisher = robot_publisher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OriginMan 网页控制服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    publisher = RobotActionPublisher()
    server = RobotHTTPServer((args.host, args.port), RobotWebHandler, publisher)

    print(f"网页控制服务已启动： http://{args.host}:{args.port}/")
    print("请在浏览器中打开该地址后点击按钮控制机器人。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭服务...")
    finally:
        server.server_close()
        publisher.shutdown()


if __name__ == "__main__":
    main()
