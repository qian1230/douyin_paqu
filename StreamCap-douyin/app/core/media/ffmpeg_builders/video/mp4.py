from ..base import FFmpegCommandBuilder


class MP4CommandBuilder(FFmpegCommandBuilder):
    def build_command(self) -> list[str]:
        command = self._get_basic_ffmpeg_command()
        if self.segment_record:
            additional_commands = [
                "-c:v", "copy",
                "-c:a", "aac",
                "-bsf:a", "aac_adtstoasc",  # 修复 ADTS→MP4 容器的 AAC 比特流
                "-map", "0",
                "-f", "segment",
                "-segment_time", str(self.segment_time),
                "-segment_format", "mp4",
                "-reset_timestamps", "1",
                "-movflags", "+frag_keyframe+empty_moov+faststart+delay_moov",
                "-flags", "global_header",
                self.full_path,
            ]
        else:
            additional_commands = [
                "-map", "0",
                "-c:v", "copy",
                "-c:a", "copy",
                "-bsf:a", "aac_adtstoasc",  # 修复 ADTS→MP4 容器的 AAC 比特流
                "-f", "mp4",
                "-movflags", "+faststart+frag_keyframe+empty_moov+delay_moov",
                self.full_path,
            ]

        command.extend(additional_commands)
        return command
