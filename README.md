# 抖音直播录制系统

## 一、系统概述

本系统是一个完整的抖音直播自动录制解决方案，能够自动爬取指定类别的直播间、录制视频、抓取弹幕数据，并实时采集直播间热度信息。

### 核心功能

- 🎬 **自动爬取**: 根据分类自动爬取抖音直播间
- 📹 **视频录制**: 使用 FFmpeg 录制直播视频
- 💬 **弹幕抓取**: 同步抓取直播间弹幕数据（对接外部弹幕脚本）
- 📊 **热度采集**: 实时采集直播间观看人数、点赞、分享等数据
- 🗄️ **数据存储**: 使用 SQLite 存储直播间信息、热度时序、弹幕日志
- 👤 **人脸检测**: 可选的人脸过滤功能

## 二、项目结构

```
StreamCap-douyin/
├── record_category.py       # 主录制脚本
├── streamcap.db             # SQLite 数据库（自动创建）
├── .env                     # 环境配置文件
├── requirements.txt         # Python 依赖
├── app/
│   ├── core/                # 核心模块
│   │   ├── scraper/         # 爬取模块
│   │   └── platforms/       # 平台处理模块
│   └── models/              # 数据模型
└── D:/zhibo-video/douyin/   # 默认视频保存目录
```

## 三、安装与配置

### 3.1 环境要求

- Python 3.11+
- FFmpeg（视频处理工具）
- 抖音网页版 Cookie

### 3.2 安装步骤

1. 安装 Python 依赖：
   ```bash
   pip install -r requirements.txt
   ```

2. 配置 FFmpeg：
   - 下载 FFmpeg 并添加到系统 PATH
   - 或修改 `record_category.py` 中的 `ffmpeg_dir` 路径

3. 配置 Cookie：
   - 在 `.env` 文件中设置 `DOUYIN_COOKIE`
   - 或通过命令行参数传入

### 3.3 环境变量配置

```env
# .env 文件示例
DOUYIN_COOKIE='your_douyin_cookie_here'
VIDEO_SAVE_PATH=D:/zhibo-video/douyin
```

## 四、使用方法

### 4.1 基本使用

```bash
# 录制娱乐类别
python record_category.py 娱乐

# 录制游戏类别
python record_category.py 游戏

# 录制二次元类别
python record_category.py 二次元
```

### 4.2 支持的类别

| 类别 | 分区ID |
|------|--------|
| 娱乐 | 202 |
| 知识 | 203 |
| 电商 | 106 |
| 二次元 | 104 |
| 游戏 | 103 |
| 运动 | 108 |
| 舞蹈 | 105 |
| 音乐 | 102 |
| 聊天 | 203 |
| 生活 | 107 |
| 文化 | 210 |

### 4.3 高级配置

在 `record_category.py` 中可以修改以下配置：

```python
MAX_RECORDING = 20        # 最大并发录制数
RECORD_DURATION = 600      # 单个视频录制时长（秒）
CHECK_INTERVAL = 150       # 检测间隔（秒）
FACE_DETECTION = False     # 是否开启人脸检测
VIDEO_SAVE_PATH = Path(r"D:\zhibo-video\douyin")  # 视频保存路径
```

## 五、输出内容

### 5.1 视频文件

视频文件按类别和直播间组织：

```
D:/zhibo-video/douyin/
├── 娱乐/
│   ├── 直播间ID1/
│   │   ├── 20260324_120000/
│   │   │   ├── 20260324_120000.mp4
│   │   │   └── danmu_直播间ID1.csv
│   └── 直播间ID2/
└── 游戏/
    └── ...
```

### 5.2 数据库表

系统自动创建以下 SQLite 表：

#### 1. `live_rooms` - 直播间基础信息

| 字段 | 类型 | 说明 |
|------|------|------|
| room_id | TEXT | 直播间ID（主键） |
| category | TEXT | 类别 |
| anchor_name | TEXT | 主播名称 |
| title | TEXT | 直播间标题 |
| first_crawl_time | TEXT | 首次爬取时间 |

#### 2. `popularity_logs` - 热度时序数据

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增ID |
| room_id | TEXT | 直播间ID |
| timestamp | TEXT | 时间戳 |
| viewer_count | INTEGER | 观看人数 |
| like_count | INTEGER | 点赞数 |
| share_count | INTEGER | 分享数 |
| gift_count | INTEGER | 礼物数 |

#### 3. `danmaku_logs` - 弹幕日志

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增ID |
| room_id | TEXT | 直播间ID |
| timestamp | TEXT | 时间戳 |
| user_name | TEXT | 用户名 |
| content | TEXT | 弹幕内容 |

#### 4. `recording_logs` - 录制日志

| 字段 | 类型 | 说明 |
|------|------|------|
| room_id | TEXT | 直播间ID |
| platform | TEXT | 平台 |
| start_time | TEXT | 开始时间 |
| end_time | TEXT | 结束时间 |
| duration | INTEGER | 录制时长（秒） |
| file_path | TEXT | 文件路径 |
| status | TEXT | 状态 |

### 5.3 弹幕 CSV 文件

弹幕数据同时保存为 CSV 文件，格式如下：

```csv
发送时间,用户ID,用户昵称,弹幕内容,当前在线人数
2026-03-24 12:00:01,123456789,用户名1,弹幕内容1,1000
2026-03-24 12:00:02,987654321,用户名2,弹幕内容2,1001
```

## 六、弹幕抓取脚本

本系统通过子进程调用外部弹幕抓取脚本：

### 6.1 关联脚本路径

```python
danmu_main = r"D:\pycharm\Project\DouyinLiveWebFetcher-main\DouyinLiveWebFetcher-main\main.py"
```

### 6.2 工作流程

1. 录制脚本启动时，同时启动弹幕抓取子进程
2. 弹幕脚本通过 WebSocket 连接抖音直播间
3. 弹幕数据实时写入 CSV 文件
4. 录制结束后，弹幕脚本自动停止

## 七、运行流程图

```
┌─────────────────────────────────────────────────────────────┐
│                    record_category.py                       │
├─────────────────────────────────────────────────────────────┤
│  1. 初始化数据库                                            │
│  2. 爬取指定类别的直播间列表                                  │
│  3. 检测每个直播间是否在直播                                  │
│  4. 人脸检测（可选）                                         │
│  5. 启动 FFmpeg 录制视频                                    │
│  6. 启动弹幕抓取子进程（main.py）                             │
│  7. 实时写入热度数据到 popularity_logs                        │
│  8. 录制完成后修复视频                                       │
│  9. 循环等待下一轮检测                                       │
└─────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                    main.py → liveMan.py                     │
├─────────────────────────────────────────────────────────────┤
│  1. 连接抖音直播间 WebSocket                                 │
│  2. 解析弹幕、礼物、点赞、进场等消息                           │
│  3. 实时写入弹幕到 CSV 文件                                   │
│  4. 120秒后自动退出                                          │
└─────────────────────────────────────────────────────────────┘
```

## 八、注意事项

### 8.1 Cookie 有效期

抖音 Cookie 有有效期，过期后需要重新获取：

1. 打开抖音直播官网：https://live.douyin.com
2. 登录账号
3. F12 → Application → Cookies → live.douyin.com
4. 复制完整 Cookie

### 8.2 防封禁措施

- 设置合理的请求间隔
- 使用等待队列避免同时请求过多
- 连续无结果时自动休眠

### 8.3 磁盘空间

- 视频文件较大，确保磁盘有足够空间
- 系统会检测磁盘空间，不足10GB时跳过视频修复

## 九、常见问题

### Q1: 录制失败怎么办？

A: 检查以下几点：
- Cookie 是否有效
- FFmpeg 是否正确配置
- 网络连接是否正常
- 保存路径是否有写入权限

### Q2: 弹幕没有抓取到？

A: 检查以下几点：
- 弹幕脚本路径是否正确
- 子进程是否正常启动
- WebSocket 连接是否成功

### Q3: 人脸检测不通过？

A: 可以关闭人脸检测：
```python
FACE_DETECTION = False
```

## 十、技术栈

- **语言**: Python 3.11+
- **视频处理**: FFmpeg
- **数据库**: SQLite3
- **网络请求**: aiohttp
- **反爬处理**: a_bogus 签名
- **弹幕抓取**: WebSocket + Protobuf

## 十一、许可证

本项目仅供学习研究使用，请勿用于商业用途。使用本项目请遵守抖音平台使用条款和相关法律法规。

---

**版本**: 1.0  
**最后更新**: 2026-7-14
注意：本仓库不包含 FFmpeg 大型 DLL 文件与视频数据集，避免仓库臃肿，使用者可自行部署 FFmpeg 环境。
