"""
biliblili弹幕解析系统
"""
import json
import queue
import struct
import threading
import time

import brotli
import flask
import websocket  # websocket-client

# 参考文档：https://github.com/lovelyyoshino/Bilibili-Live-API/blob/master/API.WebSocket.md

BILIBILI_WSS = "wss://broadcastlv.chat.bilibili.com/sub"  # 弹幕服务器地址
BILIBILI_HEAD = '>ihhii'  # 弹幕头部格式
BILIBILI_HEAD_LEN = struct.calcsize(BILIBILI_HEAD)  # 弹幕头部长度
ROOM_ID = 572418  # 房间ID
DEBUG = False

app = flask.Flask(__name__)


class BilibiliDanmu:
    """
    弹幕类
    """

    def __init__(self, data, header_length=BILIBILI_HEAD_LEN, protocol_version=0, operation=7, sequence_id=1):
        if type(data) == str:
            self.data = data.encode('utf-8')
            self.packet_length = len(data) + BILIBILI_HEAD_LEN
            self.header_length = header_length
            self.protocol_version = protocol_version
            self.operation = operation
            self.sequence_id = sequence_id
        elif type(data) == bytes:
            self.packet_length, self.header_length, self.protocol_version, self.operation, self.sequence_id, self.data = self.decode(data)
        if self.packet_length != len(self.data) + self.header_length:
            self.other_data = self.data[self.packet_length - self.header_length:]
            self.data = self.data[:self.packet_length - self.header_length]
        else:
            self.other_data = None

    def encode(self):
        """
        将数据编码为websocket格式
        """
        return struct.pack(BILIBILI_HEAD, self.packet_length, self.header_length, self.protocol_version, self.operation, self.sequence_id) + self.data

    @staticmethod
    def decode(data):
        """
        解码websocket数据
        """
        packet_length, header_length, protocol_version, operation, sequence_id = struct.unpack(BILIBILI_HEAD, data[:BILIBILI_HEAD_LEN])
        if protocol_version == 3:
            data = brotli.decompress(data[BILIBILI_HEAD_LEN:])
            packet_length, header_length, protocol_version, operation, sequence_id = struct.unpack(BILIBILI_HEAD, data[:BILIBILI_HEAD_LEN])
        return packet_length, header_length, protocol_version, operation, sequence_id, data[BILIBILI_HEAD_LEN:]

    def __str__(self):
        return f"{self.packet_length} {self.header_length} {self.protocol_version} {self.operation} {self.sequence_id} {self.data[:self.packet_length - self.header_length]}"


class BilibiliWebsocket:
    """
    弹幕Websocket类
    """

    def __init__(self, room_id):
        self.room_id = room_id
        self.ws = websocket.WebSocketApp(BILIBILI_WSS,
                                         on_open=self.on_open,
                                         on_message=self.on_message,
                                         # on_error=on_error,
                                         # on_close=on_close
                                         )
        self.danmu_list = queue.Queue()

    def put_danmu(self, danmu):
        """
        写入弹幕
        """
        if danmu.operation != 5:
            return
        # print(danmu.data.decode('utf-8'))
        self.danmu_list.put(danmu.data.decode('utf-8'))

    def get_danmu(self):
        """
        获取所有弹幕
        """
        danmu_list = []
        while self.danmu_list.empty() is False:
            danmu_list.append(self.danmu_list.get())
        return danmu_list

    def on_message(self, ws, message):
        """
        收到服务器发送的数据后触发on_message事件
        """
        danmu = BilibiliDanmu(message)
        self.put_danmu(danmu)
        while danmu.other_data:
            danmu = BilibiliDanmu(danmu.other_data)
            self.put_danmu(danmu)

    def on_open(self, ws):
        """
        建立连接后触发on_open事件
        """
        # 连接房间
        ws.send(BilibiliDanmu(json.dumps({
            "protover": 3,
            "roomid": self.room_id,
            "platform": "web",
            "type": 2,
        })).encode())

    def heartbeat(self):
        """
        心跳
        """
        while True:
            self.ws.send(BilibiliDanmu(json.dumps({}), operation=2).encode())
            time.sleep(10)

    def start(self):
        """
        启动弹幕监听服务器
        """
        # self.ws.run_forever()
        threading.Thread(target=self.ws.run_forever, kwargs={"ping_timeout": 30}).start()
        time.sleep(1)
        threading.Thread(target=self.heartbeat).start()


@app.route('/api/danmu')
def api_danmu():
    """
    获取弹幕
    """
    return_list = []
    for danmu in danmu_ws.get_danmu():
        danmu = json.loads(danmu)
        if danmu['cmd'].split(':')[0] == 'DANMU_MSG' or danmu['cmd'] == 'DANMU_MSG':
            return_list.append({'cmd': 'DANMU_MSG', 'user': danmu['info'][2][1], 'content': danmu['info'][1]})
        elif danmu['cmd'] == 'SEND_GIFT':
            return_list.append({'cmd': danmu['cmd'], 'user': danmu['data']['uname'], 'price': danmu['data']['price'] * danmu['data']['num'],
                                'coin_type': danmu['data']['coin_type']})
    return flask.jsonify({"data": return_list})


danmu_ws = BilibiliWebsocket(ROOM_ID)
danmu_ws.start()
if DEBUG:
    while True:
        time.sleep(1)
        for danmu in danmu_ws.get_danmu():
            danmu = json.loads(danmu)
            if danmu['cmd'] == 'DANMU_MSG':
                # 弹幕
                uid = danmu['info'][2][0]
                user = danmu['info'][2][1]
                content = danmu['info'][1]
                print(f'【弹幕】{user}({uid}): {content}')
            elif danmu['cmd'] == 'SEND_GIFT':
                # 礼物
                coin_type = danmu['data']['coin_type']
                gift_name = danmu['data']['giftName']
                price = danmu['data']['price']
                num = danmu['data']['num']
                uid = danmu['data']['uid']
                user = danmu['data']['uname']
                print(f'【礼物】{user}({uid}): {gift_name}({coin_type})x{num}={price * num}')
            elif danmu['cmd'] == 'COMBO_SEND':
                # 连击（没用的信息，只要看礼物就可以了）
                uid = danmu['data']['uid']
                user = danmu['data']['uname']
                combo_num = danmu['data']['combo_num']
                gift_name = danmu['data']['gift_name']
                # print(f'【连击】{user}({uid}): {combo_num}连击{gift_name}')
            elif danmu['cmd'] == 'GUARD_BUY':
                # 舰长
                uid = danmu['data']['uid']
                user = danmu['data']['uname']
                guard_level = danmu['data']['guard_level']
                num = danmu['data']['num']
                price = danmu['data']['price']
                gift_name = danmu['data']['gift_name']
            elif danmu['cmd'] in ['INTERACT_WORD', 'WATCHED_CHANGE', 'ONLINE_RANK_COUNT', 'STOP_LIVE_ROOM_LIST', 'ENTRY_EFFECT',
                                  'HOT_RANK_CHANGED_V2', 'ONLINE_RANK_V2', 'ONLINE_RANK_TOP3', 'NOTICE_MSG', 'PREPARING', 'SUPER_CHAT_MESSAGE',
                                  'WIDGET_BANNER', 'HOT_RANK_CHANGED', 'SUPER_CHAT_MESSAGE_JPN', 'USER_TOAST_MSG', 'ROOM_REAL_TIME_MESSAGE_UPDATE']:
                # 垃圾信息
                pass
            else:
                # print(json.dumps(danmu, ensure_ascii=False, indent=4))
                print(danmu)
else:
    app.run(host='0.0.0.0', port=18080)
