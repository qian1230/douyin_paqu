import json
import os
import shutil
from typing import TypeVar

import aiofiles

from ...utils.logger import logger

T = TypeVar("T")


class ConfigManager:
    def __init__(self, run_path):
        self.config_path = os.path.join(run_path, "config")
        self.language_config_path = os.path.join(self.config_path, "language.json")
        self.default_config_path = os.path.join(self.config_path, "default_settings.json")
        self.user_config_path = os.path.join(self.config_path, "user_settings.json")
        self.cookies_config_path = os.path.join(self.config_path, "cookies.json")
        self.about_config_path = os.path.join(self.config_path, "version.json")
        self.recordings_config_path = os.path.join(self.config_path, "recordings.json")
        self.accounts_config_path = os.path.join(self.config_path, "accounts.json")
        self.web_auth_config_path = os.path.join(self.config_path, "web_auth.json")

        os.makedirs(os.path.dirname(self.default_config_path), exist_ok=True)
        self.init()

    def init(self):
        self.init_default_config()
        self.init_user_config()
        self.init_cookies_config()
        self.init_accounts_config()
        self.init_recordings_config()
        self.init_web_auth_config()

    @staticmethod
    def _init_config(config_path, default_config=None):
        """Initialize a configuration file with default values if it does not exist."""
        if not os.path.exists(config_path):
            if default_config is None:
                default_config = {}
            try:
                with open(config_path, "w", encoding="utf-8") as file:
                    json.dump(default_config, file, ensure_ascii=False, indent=4)
                logger.info(f"Initialized configuration file: {config_path}")
            except Exception as e:
                logger.error(f"Failed to initialize configuration file {config_path}: {e}")

    def init_default_config(self):
        default_config = {}
        self._init_config(self.default_config_path, default_config)

    def init_user_config(self):
        # 如果文件存在，尝试加载
        if os.path.exists(self.user_config_path):
            try:
                config = self.load_user_config()
                # 如果成功加载且不为空，直接返回
                if config:
                    return
            except Exception:
                # 如果加载失败，继续执行复制操作
                pass
        
        # 文件不存在或加载失败，从默认配置复制
        try:
            shutil.copy(self.default_config_path, self.user_config_path)
        except PermissionError:
            # 如果复制权限失败，只复制文件内容（不复制权限）
            try:
                shutil.copyfile(self.default_config_path, self.user_config_path)
            except Exception as e:
                # 如果复制文件也失败，记录错误但不抛出异常
                logger.warning(f"Failed to copy default config to user config: {e}")

    def init_cookies_config(self):
        cookies_config = {}
        self._init_config(self.cookies_config_path, cookies_config)

    def init_accounts_config(self):
        cookies_config = {}
        self._init_config(self.accounts_config_path, cookies_config)

    def init_recordings_config(self):
        # recordings.json 期望是一个列表，默认写成 []，避免后续读取成 dict
        default_recordings = []
        self._init_config(self.recordings_config_path, default_recordings)

    def init_web_auth_config(self):
        cookies_config = {}
        self._init_config(self.web_auth_config_path, cookies_config)

    @staticmethod
    def _load_config(config_path, error_message):
        """Load configuration from a JSON file with retry mechanism for concurrent access."""
        import time
        max_retries = 3
        retry_delay = 0.1  # 100ms
        
        for attempt in range(max_retries):
            try:
                # 特殊处理 recordings.json 为空文件的情况：自动修复为 []
                try:
                    if os.path.basename(config_path) == "recordings.json" and os.path.exists(config_path) and os.path.getsize(config_path) == 0:
                        with open(config_path, "w", encoding="utf-8") as fix_file:
                            fix_file.write("[]")
                except Exception:
                    # 如果修复失败，不影响后续正常读取流程
                    pass

                # #region agent log
                import json as json_module
                with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"id": "log_config_load_start", "timestamp": time.time() * 1000, "location": "config_manager.py:_load_config", "message": "Loading config file", "data": {"config_path": config_path, "attempt": attempt + 1}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "A"}) + "\n")
                # #endregion
                with open(config_path, encoding="utf-8") as file:
                    content = json.load(file)
                    # #region agent log
                    with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                        f.write(json_module.dumps({"id": "log_config_load_success", "timestamp": time.time() * 1000, "location": "config_manager.py:_load_config", "message": "Config loaded successfully", "data": {"config_path": config_path, "type": type(content).__name__, "is_list": isinstance(content, list), "is_dict": isinstance(content, dict), "length": len(content) if hasattr(content, '__len__') else None}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "A"}) + "\n")
                    # #endregion
                    # recordings.json 期望始终是 list，如果意外变成 dict，这里自动修正为空列表
                    if os.path.basename(config_path) == "recordings.json" and isinstance(content, dict):
                        return []
                    return content
            except json.JSONDecodeError as e:
                # #region agent log
                import json as json_module
                with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"id": "log_config_json_error", "timestamp": time.time() * 1000, "location": "config_manager.py:_load_config", "message": "JSON decode error", "data": {"config_path": config_path, "error": str(e), "attempt": attempt + 1}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "A"}) + "\n")
                # #endregion
                if attempt < max_retries - 1:
                    # Retry if file might be being written
                    time.sleep(retry_delay)
                    continue
                # recordings.json 解析失败时，自动重置为 []
                if os.path.basename(config_path) == "recordings.json":
                    try:
                        with open(config_path, "w", encoding="utf-8") as fix_file:
                            fix_file.write("[]")
                    except Exception:
                        pass
                    logger.error(f"Invalid JSON format in file (reset to []): {config_path}")
                    return []
                logger.error(f"Invalid JSON format in file: {config_path}")
                return {}
            except (FileNotFoundError, IOError, OSError) as e:
                # #region agent log
                import json as json_module
                with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"id": "log_config_file_error", "timestamp": time.time() * 1000, "location": "config_manager.py:_load_config", "message": "File access error", "data": {"config_path": config_path, "error": str(e), "attempt": attempt + 1}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "A"}) + "\n")
                # #endregion
                if attempt < max_retries - 1:
                    # Retry if file might be locked or being written
                    time.sleep(retry_delay)
                    continue
                if isinstance(e, FileNotFoundError):
                    logger.error(f"Configuration file not found: {config_path}")
                else:
                    logger.error(f"Error accessing configuration file {config_path}: {e}")
                return {}
            except Exception as e:
                # #region agent log
                import json as json_module
                with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({"id": "log_config_other_error", "timestamp": time.time() * 1000, "location": "config_manager.py:_load_config", "message": "Other error loading config", "data": {"config_path": config_path, "error": str(e), "attempt": attempt + 1}, "sessionId": "debug-session", "runId": "run1", "hypothesisId": "A"}) + "\n")
                # #endregion
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                logger.error(f"{error_message}: {e}")
                return {}
        
        # If all retries failed
        logger.error(f"Failed to load configuration file after {max_retries} attempts: {config_path}")
        return {}

    def load_default_config(self):
        return self._load_config(self.default_config_path, "An error occurred while loading default config")

    def load_user_config(self):
        return self._load_config(self.user_config_path, "An error occurred while loading user config")

    def load_recordings_config(self):
        return self._load_config(self.recordings_config_path, "An error occurred while loading recordings config")

    def load_accounts_config(self):
        return self._load_config(self.accounts_config_path, "An error occurred while loading accounts config")

    def load_cookies_config(self):
        return self._load_config(self.cookies_config_path, "An error occurred while loading cookies config")

    def load_about_config(self):
        return self._load_config(self.about_config_path, "An error occurred while loading about config")

    def load_language_config(self):
        return self._load_config(self.language_config_path, "An error occurred while loading language config")

    def load_i18n_config(self, path):
        """Load i18n configuration from a JSON file."""
        return self._load_config(path, "An error occurred while loading i18n config")

    def load_web_auth_config(self):
        return self._load_config(self.web_auth_config_path, "An error occurred while loading web auth config")

    @staticmethod
    async def _save_config(config_path, config, success_message, error_message):
        """Save configuration to a JSON file."""
        try:
            # #region agent log
            import json as json_module
            import time as time_module
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({
                    "id": "log_config_save_start",
                    "timestamp": time_module.time() * 1000,
                    "location": "config_manager.py:_save_config",
                    "message": "Saving config file",
                    "data": {
                        "config_path": config_path,
                        "is_list": isinstance(config, list),
                        "is_dict": isinstance(config, dict),
                        "length": len(config) if hasattr(config, "__len__") else None,
                    },
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "SAVE"
                }) + "\n")
            # #endregion
            async with aiofiles.open(config_path, "w", encoding="utf-8") as file:
                await file.write(json.dumps(config, ensure_ascii=False, indent=4))
            # 立刻回读一次，确认磁盘上的实际内容长度
            try:
                with open(config_path, encoding="utf-8") as verify_file:
                    import json as json_module
                    content = json_module.load(verify_file)
                    verify_len = len(content) if hasattr(content, "__len__") else None
            except Exception as ve:
                verify_len = None
                # #region agent log
                import json as json_module
                import time as time_module
                with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                    f.write(json_module.dumps({
                        "id": "log_config_save_verify_error",
                        "timestamp": time_module.time() * 1000,
                        "location": "config_manager.py:_save_config",
                        "message": "Error verifying saved config",
                        "data": {"config_path": config_path, "error": str(ve)},
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "SAVE_VERIFY"
                    }) + "\n")
                # #endregion
            # #region agent log
            import json as json_module
            import time
            with open('/home/usr/zhz/StreamCap-main/.cursor/debug.log', 'a') as f:
                f.write(json_module.dumps({
                    "id": "log_config_save_success",
                    "timestamp": time.time() * 1000,
                    "location": "config_manager.py:_save_config",
                    "message": "Config saved successfully",
                    "data": {
                        "config_path": config_path,
                        "is_list": isinstance(config, list),
                        "is_dict": isinstance(config, dict),
                        "length": len(config) if hasattr(config, "__len__") else None,
                        "verify_length": verify_len if 'verify_len' in locals() else None,
                    },
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "SAVE"
                }) + "\n")
            # #endregion
            logger.info(success_message)
        except Exception as e:
            logger.error(f"{error_message}: {e}")

    async def save_recordings_config(self, config):
        await self._save_config(
            self.recordings_config_path,
            config,
            success_message="Recordings configuration saved.",
            error_message="An error occurred while saving recordings config",
        )

    async def save_accounts_config(self, config):
        await self._save_config(
            self.accounts_config_path,
            config,
            success_message="Accounts configuration saved.",
            error_message="An error occurred while saving accounts config",
        )

    async def save_web_auth_config(self, config):
        await self._save_config(
            self.web_auth_config_path,
            config,
            success_message="Web auth configuration saved.",
            error_message="An error occurred while saving web auth config",
        )

    async def save_user_config(self, config):
        await self._save_config(
            self.user_config_path,
            config,
            success_message="User configuration saved.",
            error_message="An error occurred while saving user config",
        )

    async def save_cookies_config(self, config):
        await self._save_config(
            self.cookies_config_path,
            config,
            success_message="Cookies configuration saved.",
            error_message="An error occurred while saving cookies config",
        )

    def get_config_value(self, key: str, default: T = None) -> T:
        user_config = self.load_user_config()
        default_config = self.load_default_config()
        return user_config.get(key, default_config.get(key, default))
