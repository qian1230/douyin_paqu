import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path("streamcap.db")
VIDEO_ROOT = Path(r"D:\zhibo-video\douyin")

def export_room_all_csv(room_id, category):
    room_dir = VIDEO_ROOT / category / room_id
    room_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))

    # 1. 导出弹幕csv
    danmu_df = pd.read_sql("""
        SELECT timestamp, user_name, content 
        FROM danmaku_logs WHERE room_id = ?
    """, conn, params=(room_id,))
    danmu_df.to_csv(room_dir / f"{room_id}_danmaku.csv", index=False, encoding="utf-8-sig")

    # 2. 导出热度时序csv
    pop_df = pd.read_sql("""
        SELECT timestamp, viewer_count, like_count, share_count, gift_count 
        FROM popularity_logs WHERE room_id = ?
    """, conn, params=(room_id,))
    pop_df.to_csv(room_dir / f"{room_id}_popularity.csv", index=False, encoding="utf-8-sig")

    # 3. 导出直播间基础信息
    room_df = pd.read_sql("SELECT * FROM live_rooms WHERE room_id = ?", conn, params=(room_id,))
    room_df.to_csv(room_dir / f"{room_id}_room_meta.csv", index=False, encoding="utf-8-sig")
    conn.close()
    print(f"✅ {room_id} 弹幕/热度/元数据CSV导出完成")

if __name__ == "__main__":
    target_category = "生活" # 修改为你采集的类别
    conn = sqlite3.connect(str(DB_PATH))
    all_rooms = pd.read_sql("SELECT DISTINCT room_id FROM live_rooms WHERE category = ?", conn, params=(target_category,))
    for rid in all_rooms["room_id"]:
        export_room_all_csv(rid, target_category)