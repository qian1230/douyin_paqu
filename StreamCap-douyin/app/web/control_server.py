import asyncio
import websockets
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ControlServer:
    def __init__(self, recorder):
        self.recorder = recorder
        self.running = False
        self.tasks = []
    
    async def handle_message(self, websocket, path):
        async for message in websocket:
            try:
                data = json.loads(message)
                command = data.get('command')
                
                if command == 'start':
                    if not self.running:
                        self.running = True
                        self.tasks.append(asyncio.create_task(self.recorder.run_forever()))
                        await websocket.send(json.dumps({'status': 'success', 'message': '录制已开始'}))
                        logger.info('录制已开始')
                    else:
                        await websocket.send(json.dumps({'status': 'error', 'message': '录制已在运行'}))
                
                elif command == 'stop':
                    if self.running:
                        self.running = False
                        # 取消所有任务
                        for task in self.tasks:
                            task.cancel()
                        self.tasks = []
                        await websocket.send(json.dumps({'status': 'success', 'message': '录制已停止'}))
                        logger.info('录制已停止')
                    else:
                        await websocket.send(json.dumps({'status': 'error', 'message': '录制未在运行'}))
                
                elif command == 'status':
                    status = 'running' if self.running else 'idle'
                    await websocket.send(json.dumps({'status': 'success', 'data': status}))
                
                else:
                    await websocket.send(json.dumps({'status': 'error', 'message': '未知命令'}))
                    
            except Exception as e:
                logger.error(f'处理消息出错: {e}')
                await websocket.send(json.dumps({'status': 'error', 'message': str(e)}))

async def start_control_server(recorder):
    server = ControlServer(recorder)
    
    async with websockets.serve(server.handle_message, "127.0.0.1", 6008):
        await asyncio.Future()  # 运行直到被终止