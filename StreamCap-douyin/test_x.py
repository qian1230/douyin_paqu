import os
import subprocess
import whisper
import pandas as pd

# ========== 配置 ==========
ROOT_VIDEO = r"D:\zhibo-video\douyin"
WHISPER_MODEL_SIZE = "base"
SKIP_EXIST = True
TMP_AUDIO_DIR = r"D:\tmp_audio_cache"
os.makedirs(TMP_AUDIO_DIR, exist_ok=True)

print(f"加载Whisper模型：{WHISPER_MODEL_SIZE}")
model = whisper.load_model(WHISPER_MODEL_SIZE)


def extract_audio(video_path, audio_out):
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "-threads", "4",
        audio_out
    ]
    # stdout/stderr直接丢弃，不做文本解码，解决GBK编码崩溃
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError("bad_video")


def run_whisper(audio_path: str):
    result = model.transcribe(
        audio_path,
        language="zh",
        verbose=False,
        fp16=False,
        beam_size=3,
        best_of=3
    )
    rows = []
    for seg in result["segments"]:
        rows.append({
            "start": round(seg["start"], 2),
            "end": round(seg["end"], 2),
            "text": seg["text"].strip()
        })
    return pd.DataFrame(rows)


def scan_and_recognize(base_dir):
    for category in os.listdir(base_dir):
        cat_path = os.path.join(base_dir, category)
        if not os.path.isdir(cat_path):
            continue
        print(f"\n==== 分类：{category} ====")
        for live_id in os.listdir(cat_path):
            live_path = os.path.join(cat_path, live_id)
            if not os.path.isdir(live_path):
                continue
            for time_folder in os.listdir(live_path):
                time_path = os.path.join(live_path, time_folder)
                if not os.path.isdir(time_path):
                    continue
                for fname in os.listdir(time_path):
                    if not fname.lower().endswith(".mp4"):
                        continue
                    video_full = os.path.join(time_path, fname)
                    csv_name = os.path.splitext(fname)[0] + "_whisper.csv"
                    csv_full = os.path.join(time_path, csv_name)

                    if SKIP_EXIST and os.path.exists(csv_full):
                        print(f"✅ 已存在，跳过：{video_full}")
                        continue

                    print(f"🎙️ 识别：{video_full}")
                    temp_wav = os.path.join(TMP_AUDIO_DIR, os.path.splitext(fname)[0] + ".wav")
                    try:
                        extract_audio(video_full, temp_wav)
                        df_sub = run_whisper(temp_wav)
                        df_sub.to_csv(csv_full, index=False, encoding="utf-8-sig")
                        print(f"📄 输出：{csv_full}")
                    except RuntimeError:
                        print(f"❌ 视频损坏(moov缺失)，跳过：{video_full}")
                    except Exception as e:
                        print(f"❌ 其他识别失败 {video_full} | {str(e)[:150]}")
                    finally:
                        if os.path.exists(temp_wav):
                            os.remove(temp_wav)


if __name__ == "__main__":
    scan_and_recognize(ROOT_VIDEO)
    print("\n===== 全部任务结束 =====")