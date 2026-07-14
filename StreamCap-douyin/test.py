import os
import re
import shutil
import pandas as pd
import numpy as np
import emoji
import chardet
from datetime import datetime
from opencc import OpenCC
from tqdm import tqdm
import ffmpeg

# ===================== 配置项 =====================
ROOT_PATH = r"D:\zhibo-video\douyin"
CLEAN_OUTPUT_PATH = r"D:\zhibo-video\douyin_cleaned"
REPORT_PATH = r"D:\zhibo-video\douyin_data_evaluation_report.xlsx"
STATISTICS_PATH = r"D:\zhibo-video\douyin_category_statistics.xlsx"

# 初始化工具
cc_s2t = OpenCC('s2t')
cc_t2s = OpenCC('t2s')
DOUYIN_EMOJI_PATTERN = re.compile(r'\[([^\]]+)\]')

# ===================== 1. 基础工具函数 =====================
def is_video_valid(video_path):
    if video_path is None or not os.path.exists(video_path):
        return False
    try:
        probe = ffmpeg.probe(video_path)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        return video_stream is not None
    except Exception as e:
        print(f"视频检查失败 {video_path}: {str(e)}")
        return False

def get_video_duration(video_path):
    if not is_video_valid(video_path):
        return 0
    try:
        probe = ffmpeg.probe(video_path)
        return float(probe['format']['duration'])
    except Exception:
        return 0

def is_csv_has_valid_data(csv_path):
    if not os.path.exists(csv_path):
        return False
    try:
        with open(csv_path, 'rb') as f:
            encoding = chardet.detect(f.read())['encoding']
        df = pd.read_csv(csv_path, encoding=encoding)
        if len(df) == 0:
            return False
        if df['弹幕内容'].isna().all() or (df['弹幕内容'].astype(str).str.strip() == '').all():
            return False
        return True
    except Exception as e:
        print(f"CSV检查失败 {csv_path}: {str(e)}")
        return False

def delete_empty_live_rooms():
    print("\n===== 第一步：扫描无有效数据直播间（仅打印，不执行删除） =====")
    for category in os.listdir(ROOT_PATH):
        category_path = os.path.join(ROOT_PATH, category)
        if not os.path.isdir(category_path):
            continue
        print(f"正在检查分类：{category}")
        for live_room_id in os.listdir(category_path):
            live_room_path = os.path.join(category_path, live_room_id)
            if not os.path.isdir(live_room_path):
                continue
            has_valid_data = False
            for timestamp_dir in os.listdir(live_room_path):
                timestamp_path = os.path.join(live_room_path, timestamp_dir)
                if not os.path.isdir(timestamp_path):
                    continue
                csv_files = [f for f in os.listdir(timestamp_path) if f.endswith('.csv') and f.startswith('danmu_')]
                for csv_file in csv_files:
                    csv_path = os.path.join(timestamp_path, csv_file)
                    if is_csv_has_valid_data(csv_path):
                        has_valid_data = True
                        break
                if has_valid_data:
                    break
            if not has_valid_data:
                print(f"🗑️ 【待删除，测试跳过】直播间：{live_room_path}")

# ===================== 2. 增强清洗函数（新版全维度清洗） =====================
def clean_spam_symbol(text):
    # 清理链接、@用户、长串符号、礼物标签
    text = re.sub(r'http[s]?://\S+', '', text)
    text = re.sub(r'@\S+', '', text)
    text = re.sub(r'\[(飞机|火箭|嘉年华|小心心|跑车|游艇|礼物)\]', '[表情]', text)
    text = re.sub(r'[!#￥%&*~.]{3,}', ' ', text)
    return text

def clean_text(text):
    if pd.isna(text):
        return ""
    text = str(text).strip()
    text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text

def normalize_emoji(text):
    if pd.isna(text):
        return ""
    text = str(text)
    matches = DOUYIN_EMOJI_PATTERN.findall(text)
    for m in matches:
        text = text.replace(f"[{m}]", "[表情]")
    text = emoji.demojize(text, delimiters=("[表情:", "]"))
    return text

def traditional_to_simplified(text):
    if pd.isna(text):
        return ""
    return cc_t2s.convert(str(text))

def standardize_time(time_str):
    if pd.isna(time_str):
        return ""
    time_str = str(time_str).strip()
    try:
        dt = datetime.strptime(time_str, "%Y/%m/%d %H:%M")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return time_str

# ===================== 3. 新增高级标注函数 =====================
def is_nonsense_text(text):
    # 判断是否纯数字/纯符号/无意义内容
    clean = text.replace("[表情]", "").strip()
    if len(clean) <= 0:
        return True
    if re.fullmatch(r'[0-9\W_]+', clean):
        return True
    return False

def get_text_length_tag(text):
    clean = text.replace("[表情]", "").strip()
    if len(clean) <= 1:
        return "极短文本"
    elif len(clean) > 200:
        return "超长刷屏文本"
    return "正常文本"

def get_ad_confidence(text):
    high = {'微信','QQ','加我','私我','群','资源','资料','接单'}
    mid = {'下单','优惠','代购','货源','链接','福利'}
    if any(k in text for k in high):
        return 1
    elif any(k in text for k in mid):
        return 0.5
    return 0

def get_sentiment_tag(text):
    pos = {'厉害','好看','支持','加油','不错','完美','牛逼','可以','太棒了'}
    neg = {'垃圾','不行','没意思','劝退','烂','无语','太差','恶心'}
    if any(k in text for k in pos):
        return "正向"
    elif any(k in text for k in neg):
        return "负向"
    return "中性"

def annotate_message_type(row):
    content = str(row['弹幕内容_表情归一']).strip()
    if content == "":
        return "无效弹幕"
    emoji_count = content.count("[表情]")
    if emoji_count / len(content) > 0.5:
        return "表情弹幕"
    interact_keywords = {'666', '哈哈哈', '哈哈', '牛逼', '厉害', '支持', '加油', '冲', '顶'}
    if any(k in content for k in interact_keywords):
        return "互动弹幕"
    ad_keywords = {'微信', 'QQ', '群', '福利', '优惠', '下单', '淘宝', '拼多多'}
    if any(k in content for k in ad_keywords):
        return "广告弹幕"
    question_keywords = {'？', '?', '怎么', '什么', '为什么', '哪里', '多少钱'}
    if any(k in content for k in question_keywords):
        return "提问弹幕"
    return "普通弹幕"

def calc_user_msg_cnt(uid, user_df):
    return len(user_df[user_df['用户ID'] == uid])

# ===================== 4. 质量评估 =====================
def evaluate_data_quality(df, live_room_id, category):
    total_rows = len(df)
    if total_rows == 0:
        return {
            '直播间ID': live_room_id,
            '分类': category,
            '总弹幕数': 0,
            '数据完整性(%)': 0,
            '有效弹幕占比(%)': 0,
            '重复数据占比(%)': 0,
            '异常值占比(%)': 0,
            '用户ID有效率(%)': 0,
            '质量评级': '不合格'
        }
    completeness = (df.notna().sum() / total_rows).mean() * 100
    valid_content_count = len(df[df['弹幕内容_表情归一'].astype(str).str.strip() != ""])
    valid_content_rate = valid_content_count / total_rows * 100
    duplicate_count = df.duplicated().sum()
    duplicate_rate = duplicate_count / total_rows * 100
    abnormal_count = 0
    if "当前在线人数" in df.columns:
        abnormal_count += len(df[(df['当前在线人数'] < 0) | (df['当前在线人数'] > 1000000)])
    abnormal_time_count = len(df[df['发送时间'] != df['标准化时间']])
    abnormal_count += abnormal_time_count
    abnormal_rate = abnormal_count / total_rows * 100
    df['用户ID字符串'] = df['用户ID'].astype(str)
    valid_user_id_count = len(df[df['用户ID字符串'].str.len() > 5])
    valid_user_id_rate = valid_user_id_count / total_rows * 100

    if completeness >= 95 and valid_content_rate >= 90 and duplicate_rate < 5 and abnormal_rate < 5:
        quality_level = '优秀'
    elif completeness >= 85 and valid_content_rate >= 80 and duplicate_rate < 10 and abnormal_rate < 10:
        quality_level = '良好'
    elif completeness >= 70 and valid_content_rate >= 60 and duplicate_rate < 20 and abnormal_rate < 20:
        quality_level = '合格'
    else:
        quality_level = '不合格'
    return {
        '直播间ID': live_room_id,
        '分类': category,
        '总弹幕数': total_rows,
        '数据完整性(%)': round(completeness, 2),
        '有效弹幕占比(%)': round(valid_content_rate, 2),
        '重复数据占比(%)': round(duplicate_rate, 2),
        '异常值占比(%)': round(abnormal_rate, 2),
        '用户ID有效率(%)': round(valid_user_id_rate, 2),
        '质量评级': quality_level
    }

# ===================== 5. 单直播间处理【终极完整版】 =====================
def process_single_live_room(csv_path, video_path, live_room_id, category):
    print(f"\n===== 处理直播间：{live_room_id} | 分类：{category} =====")
    with open(csv_path, 'rb') as f:
        encoding = chardet.detect(f.read())['encoding']
    df = pd.read_csv(csv_path, encoding=encoding)
    print(f"原始数据行数：{len(df)}")

    # 基础清洗
    df = df.dropna(subset=['弹幕内容', '用户ID'], how='all')
    df['用户ID'] = df['用户ID'].astype(str).str.rstrip('.0')
    df['标准化时间'] = df['发送时间'].apply(standardize_time)

    # 兼容缺失在线人数列
    if "当前在线人数" not in df.columns:
        df['当前在线人数'] = 0
    else:
        df['当前在线人数'] = pd.to_numeric(df['当前在线人数'], errors='coerce').fillna(0).astype(int)

    # 用户活跃度
    user_stat_df = df[['用户ID']].copy()
    df['用户弹幕数'] = df['用户ID'].apply(lambda x: calc_user_msg_cnt(x, user_stat_df))
    df['用户活跃度等级'] = df['用户弹幕数'].apply(lambda x: '高活跃' if x >= 10 else '中活跃' if x >= 3 else '低活跃')

    # ========== 增强清洗流水线（全新升级） ==========
    df['弹幕内容_清洗后'] = df['弹幕内容'].apply(clean_text)
    df['弹幕内容_净化去噪'] = df['弹幕内容_清洗后'].apply(clean_spam_symbol)
    df['弹幕内容_简繁统一'] = df['弹幕内容_净化去噪'].apply(traditional_to_simplified)
    df['弹幕内容_表情归一'] = df['弹幕内容_简繁统一'].apply(normalize_emoji)

    # 高级标签
    df['是否无意义文本'] = df['弹幕内容_表情归一'].apply(is_nonsense_text)
    df['文本长度标签'] = df['弹幕内容_表情归一'].apply(get_text_length_tag)
    df['广告置信度'] = df['弹幕内容_表情归一'].apply(get_ad_confidence)
    df['弹幕情绪'] = df['弹幕内容_表情归一'].apply(get_sentiment_tag)
    df['弹幕类型'] = df.apply(annotate_message_type, axis=1)

    # 重复刷屏统计
    dup_count_series = df.groupby('弹幕内容_表情归一')['弹幕内容_表情归一'].transform('count')
    df['本条弹幕重复次数'] = dup_count_series
    df['是否刷屏弹幕'] = df['本条弹幕重复次数'] >= 5

    # 【终极标签：高质量可用样本】
    df['可用训练样本'] = (
        (~df['是否无意义文本']) &
        (~df['是否刷屏弹幕']) &
        (df['广告置信度'] == 0) &
        (df['文本长度标签'] == '正常文本')
    )

    # 质量评估
    quality_report = evaluate_data_quality(df, live_room_id, category)

    # 视频信息
    video_valid = is_video_valid(video_path)
    video_duration = get_video_duration(video_path) if video_valid else 0
    quality_report['视频是否正常'] = video_valid
    quality_report['视频时长(秒)'] = round(video_duration, 2)
    quality_report['弹幕密度(条/分钟)'] = round(len(df) / (video_duration / 60), 2) if video_duration > 0 else 0

    # 新增统计：高质量样本数
    quality_report['高质量可用样本数'] = df['可用训练样本'].sum()
    quality_report['无意义弹幕数'] = df['是否无意义文本'].sum()
    quality_report['广告弹幕数'] = (df['广告置信度'] > 0).sum()
    quality_report['刷屏弹幕数'] = df['是否刷屏弹幕'].sum()

    # 输出最终清洗文件
    output_dir = os.path.join(CLEAN_OUTPUT_PATH, category, live_room_id)
    os.makedirs(output_dir, exist_ok=True)
    output_csv_path = os.path.join(output_dir, f"danmu_cleaned_{live_room_id}.csv")
    df.to_csv(output_csv_path, index=False, encoding='utf-8-sig')
    print(f"✅ 清洗后数据已保存至：{output_csv_path}")
    return quality_report, len(df), video_duration

# ===================== 6. 主流程 =====================
def main():
    delete_empty_live_rooms()
    print("\n===== 第二步：全量数据清洗与处理（仅输出新文件，原始数据不变） =====")
    all_quality_reports = []
    category_statistics = []
    for category in os.listdir(ROOT_PATH):
        category_path = os.path.join(ROOT_PATH, category)
        if not os.path.isdir(category_path):
            continue
        print(f"\n===== 处理分类：{category} =====")
        total_danmu_count = 0
        total_video_duration = 0
        total_valid_sample = 0
        live_room_count = 0
        valid_live_room_count = 0
        for live_room_id in tqdm(os.listdir(category_path)):
            live_room_path = os.path.join(category_path, live_room_id)
            if not os.path.isdir(live_room_path):
                continue
            csv_path = None
            video_path = None
            for timestamp_dir in os.listdir(live_room_path):
                timestamp_path = os.path.join(live_room_path, timestamp_dir)
                if not os.path.isdir(timestamp_path):
                    continue
                csv_files = [f for f in os.listdir(timestamp_path) if f.endswith('.csv') and f.startswith('danmu_')]
                if csv_files:
                    csv_path = os.path.join(timestamp_path, csv_files[0])
                video_files = [f for f in os.listdir(timestamp_path) if f.endswith('.mp4')]
                if video_files:
                    video_path = os.path.join(timestamp_path, video_files[0])
                if csv_path and video_path:
                    break
            if not csv_path or not os.path.exists(csv_path):
                print(f"⚠️  直播间 {live_room_id} 无有效CSV文件，跳过")
                continue
            try:
                quality_report, danmu_count, video_duration = process_single_live_room(csv_path, video_path, live_room_id, category)
                all_quality_reports.append(quality_report)
                live_room_count += 1
                if quality_report['质量评级'] != '不合格':
                    valid_live_room_count += 1
                total_danmu_count += danmu_count
                total_video_duration += video_duration
                total_valid_sample += quality_report['高质量可用样本数']
            except Exception as e:
                print(f"❌ 处理直播间 {live_room_id} 失败：{str(e)}")
                continue
        category_statistics.append({
            '分类': category,
            '直播间总数': live_room_count,
            '有效直播间数': valid_live_room_count,
            '有效直播间占比(%)': round(valid_live_room_count / live_room_count * 100, 2) if live_room_count > 0 else 0,
            '总弹幕数': total_danmu_count,
            '高质量样本总数': total_valid_sample,
            '总直播时长(秒)': round(total_video_duration, 2),
            '平均弹幕密度(条/分钟)': round(total_danmu_count / (total_video_duration / 60), 2) if total_video_duration > 0 else 0
        })

    print("\n===== 第三步：输出评估报告与统计结果 =====")
    quality_df = pd.DataFrame(all_quality_reports)
    quality_df.to_excel(REPORT_PATH, index=False)
    print(f"✅ 数据质量评估报告已保存至：{REPORT_PATH}")
    statistics_df = pd.DataFrame(category_statistics)
    statistics_df.to_excel(STATISTICS_PATH, index=False)
    print(f"✅ 分类统计结果已保存至：{STATISTICS_PATH}")
    print("\n 运行完成！")

if __name__ == "__main__":
    main()