import websocket
import gzip
import threading
import sqlite3
from datetime import datetime

from proto import dy_pb2


class DouyinDanmaku:

    def __init__(self, room_id, ws_url, cookie):

        self.room_id = room_id
        self.ws_url = ws_url
        self.cookie = cookie


    def start(self):

        print("连接:")
        print(self.ws_url)


        headers=[
            f"Cookie:{self.cookie}",
            "User-Agent:Mozilla/5.0",
            "Origin:https://live.douyin.com"
        ]


        self.ws = websocket.create_connection(
            self.ws_url,
            header=headers
        )


        print(" websocket连接成功")


        while True:

            data=self.ws.recv()

            if not data:
                continue


            self.decode(data)



    def decode(self,data):

        try:

            frame=dy_pb2.PushFrame()

            frame.ParseFromString(data)


            payload=gzip.decompress(frame.payload)


            response=dy_pb2.Response()

            response.ParseFromString(payload)


            for msg in response.messagesList:

                if msg.method=="WebcastChatMessage":

                    chat=dy_pb2.ChatMessage()

                    chat.ParseFromString(msg.payload)


                    print(
                        datetime.now(),
                        chat.user.nickName,
                        ":",
                        chat.content
                    )


        except Exception as e:

            print("解析失败",e)