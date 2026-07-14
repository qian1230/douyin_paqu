import sqlite3
import time

conn = sqlite3.connect('streamcap.db')
while True:
    result = conn.execute('SELECT category, COUNT(*) FROM scraped_rooms GROUP BY category').fetchall()
    print(f"\n{time.strftime('%H:%M:%S')} - 各分区数量:")
    for cat, count in result:
        print(f"  {cat}: {count}")
    time.sleep(60)
