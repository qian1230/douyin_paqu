# main.py
import sys
import time
from liveMan import DouyinLiveWebFetcher

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("用法：python main.py 直播间live_id 弹幕保存csv完整路径")
        exit(1)
    live_id_arg = sys.argv[1]
    csv_path_arg = sys.argv[2]
    fetcher = DouyinLiveWebFetcher(live_id=live_id_arg, csv_save_path=csv_path_arg)

    # 录制固定120秒，弹幕同步运行120秒后自动退出
    import threading


    def auto_close():
        time.sleep(120)
        fetcher.stop()
        print("录制时长结束，弹幕抓取进程自动关闭")


    threading.Thread(target=auto_close, daemon=True).start()

    fetcher.start()