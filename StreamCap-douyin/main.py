#!/usr/bin/env python3
"""
StreamCap 主程序 - 增强调试版
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
import json as json_module
import time
from datetime import datetime

# ========== 调试配置 ==========
DEBUG_MODE = True  # 设置为 True 开启详细调试
DEBUG_LOG_FILE = "main_debug.log"
# =============================

# 配置详细日志
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.WARNING,
    format='%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(DEBUG_LOG_FILE),
        logging.StreamHandler()
    ]
)

# 创建调试日志器
debug_logger = logging.getLogger("DEBUG")
debug_logger.setLevel(logging.DEBUG)

# 记录启动信息
debug_logger.debug("=" * 80)
debug_logger.debug(f"StreamCap 启动 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
debug_logger.debug(f"Python 版本: {sys.version}")
debug_logger.debug(f"工作目录: {os.getcwd()}")
debug_logger.debug(f"命令行参数: {sys.argv}")
debug_logger.debug("=" * 80)

# Silence noisy libs (但保留调试信息)
logging.getLogger('flet_core').setLevel(logging.DEBUG if DEBUG_MODE else logging.WARNING)
logging.getLogger('httpx').setLevel(logging.DEBUG if DEBUG_MODE else logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.DEBUG if DEBUG_MODE else logging.WARNING)
logging.getLogger('asyncio').setLevel(logging.DEBUG if DEBUG_MODE else logging.WARNING)

# Focus logs on scrapers
logging.getLogger('app.core.scraper').setLevel(logging.DEBUG if DEBUG_MODE else logging.INFO)
logging.getLogger('app.core.scraper.platforms').setLevel(logging.DEBUG if DEBUG_MODE else logging.INFO)
logging.getLogger('app.core.scheduler').setLevel(logging.DEBUG if DEBUG_MODE else logging.WARNING)

# Ensure scraper logs are emitted
_scraper_formatter = logging.Formatter(
    '%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
for _name in ('app.core.scraper', 'app.core.scraper.platforms', 'app.core.scheduler', 'DEBUG'):
    _logger = logging.getLogger(_name)
    if not _logger.handlers:
        _h = logging.StreamHandler()
        _h.setLevel(logging.DEBUG if DEBUG_MODE else logging.INFO)
        _h.setFormatter(_scraper_formatter)
        _logger.addHandler(_h)
        _logger.propagate = False

import flet as ft
from dotenv import load_dotenv
from screeninfo import get_monitors

# Add project root to path
sys.path.append(str(Path(__file__).parent.resolve()))
debug_logger.debug(f"添加项目路径: {Path(__file__).parent.resolve()}")

from app.app_manager import App, execute_dir
from app.auth.auth_manager import AuthManager
from app.core.scheduler.recording_scheduler import RecordingScheduler
from app.core.recording.record_manager import RecordingManager
from app.db.base import create_tables
from app.db.session import engine
from app.lifecycle.app_close_handler import handle_app_close
from app.lifecycle.tray_manager import TrayManager
from app.ui.components.common.save_progress_overlay import SaveProgressOverlay
from app.ui.layout.responsive_layout import setup_responsive_layout
from app.ui.views.login_view import LoginPage
from app.utils.logger import logger

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6006
WINDOW_SCALE = 0.65
MIN_WIDTH = 950
ASSETS_DIR = "assets"


class GlobalState:
    periodic_tasks_started = False


global_state = GlobalState()


def debug_print(msg, level="INFO"):
    """统一的调试输出函数"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [{level}] {msg}")
    if DEBUG_MODE:
        debug_logger.debug(msg)


def setup_window(page: ft.Page, app: App, is_web: bool) -> None:
    """Set up the application window with proper dimensions and settings"""
    debug_print(f"设置窗口 - is_web: {is_web}")
    
    # Set default window settings
    page.window.icon = os.path.join(execute_dir, ASSETS_DIR, "icon.ico")
    page.window.to_front()
    page.window.skip_task_bar = False
    page.window.always_on_top = False
    page.focused = True

    # Default window dimensions
    default_width = 1280
    default_height = 800
    
    if not is_web:
        try:
            # Try to get saved window size from settings
            if app.settings.user_config.get("remember_window_size"):
                window_width = app.settings.user_config.get("window_width")
                window_height = app.settings.user_config.get("window_height")
                if window_width and window_height:
                    page.window.width = int(window_width)
                    page.window.height = int(window_height)
                    debug_print(f"使用保存的窗口大小: {window_width}x{window_height}")
                    return

            # Try to detect screen size
            try:
                from screeninfo import get_monitors
                monitors = get_monitors()
                if monitors:
                    screen = monitors[0]
                    screen_width = screen.width
                    screen_height = screen.height
                    logger.info(f"Detected screen resolution: {screen_width}x{screen_height}")
                    debug_print(f"检测到屏幕分辨率: {screen_width}x{screen_height}")
                    
                    # Calculate window size as a percentage of screen size
                    WINDOW_SCALE = 0.8  # 80% of screen size
                    page.window.width = int(screen_width * WINDOW_SCALE)
                    page.window.height = int(screen_height * WINDOW_SCALE)
                    debug_print(f"设置窗口大小为: {page.window.width}x{page.window.height}")
                    return
            except Exception as e:
                logger.warning(f"Could not detect screen size: {e}")
                debug_print(f"检测屏幕大小失败: {e}", "WARNING")
            
            # Fallback to default dimensions
            page.window.width = default_width
            page.window.height = default_height
            debug_print(f"使用默认窗口大小: {default_width}x{default_height}")
            
        except Exception as e:
            logger.error(f"Error setting up window: {e}")
            debug_print(f"设置窗口出错: {e}", "ERROR")
            page.window.width = default_width
            page.window.height = default_height


def get_route_handler() -> dict[str, str]:
    routes = {
        "/": "home",
        "/home": "home",
        "/recordings": "recordings",
        "/settings": "settings",
        "/storage": "storage",
        "/about": "about",
    }
    debug_print(f"路由配置: {routes}")
    return routes


def handle_route_change(page: ft.Page, app: App) -> callable:
    route_map = get_route_handler()

    def route_change(e: ft.RouteChangeEvent) -> None:
        debug_print(f"路由变化: {e.route}")
        tr = ft.TemplateRoute(e.route)
        page_name = route_map.get(tr.route)
        if page_name:
            debug_print(f"切换到页面: {page_name}")
            page.run_task(app.switch_page, page_name)
        else:
            logger.warning(f"Unknown route: {e.route}, redirecting to /")
            debug_print(f"未知路由: {e.route}, 重定向到 /", "WARNING")
            page.go("/")

    return route_change


def handle_window_event(page: ft.Page, app: App, save_progress_overlay: 'SaveProgressOverlay') -> callable:
    async def on_window_event(e: ft.ControlEvent) -> None:
        debug_print(f"窗口事件: {e.data}")
        if e.data == "close":
            debug_print("收到窗口关闭事件")
            if app.settings.user_config.get("remember_window_size"):
                app.settings.user_config["window_width"] = page.window.width
                app.settings.user_config["window_height"] = page.window.height
                debug_print(f"保存窗口大小: {page.window.width}x{page.window.height}")
                await app.config_manager.save_user_config(app.settings.user_config)
            await handle_app_close(page, app, save_progress_overlay)

    return on_window_event


def handle_disconnect(page: ft.Page, app: App) -> callable:
    """Handle disconnection for web mode."""

    async def disconnect(_: ft.ControlEvent) -> None:
        debug_print("客户端断开连接")
        page.pubsub.unsubscribe_all()
        app.settings.user_config["last_route"] = page.route
        await app.config_manager.save_user_config(app.settings.user_config)
        logger.info(f"Saved last route: {page.route}")
        debug_print(f"保存最后路由: {page.route}")

    return disconnect


def handle_page_resize(page: ft.Page, app: App) -> callable:
    """handle page resize"""

    def on_resize(_: ft.ControlEvent) -> None:
        debug_print(f"页面大小变化: {page.width}x{page.height}")
        setup_responsive_layout(page, app)
        page.update()

    return on_resize


async def main(page: ft.Page) -> None:
    debug_print("=" * 60)
    debug_print("🎬 main() 函数开始执行")
    debug_print("=" * 60)
    
    # Set window properties
    page.title = "StreamCap"
    page.theme_mode = ft.ThemeMode.DARK
    page.window_width = 1280
    page.window_height = 720
    page.window_resizable = True
    page.window_maximized = True
    page.padding = 0
    page.margin = 0
    page.window_center = True
    debug_print(f"页面标题: {page.title}")
    debug_print(f"窗口大小: {page.window_width}x{page.window_height}")

    # Initialize the database first
    debug_print("初始化数据库...")
    await init_db()
    debug_print("数据库初始化完成")

    # Initialize the app
    debug_print("创建 App 实例...")
    app = App(page)
    debug_print(f"App 实例创建完成: {app}")

    # Determine if running in web mode
    is_web = getattr(args, 'web', False) or os.getenv("PLATFORM") == "web"
    app.is_web_mode = is_web
    app.is_mobile = False
    debug_print(f"运行模式: {'Web' if is_web else 'Desktop'}")

    # For desktop mode, add the app to the page and start tasks here
    # For web mode, let load_app handle everything to avoid duplication
    if not is_web:
        debug_print("桌面模式: 添加页面并启动任务")
        # Add the app to the page
        page.add(app.complete_page)

        # Update the page
        await page.update_async() if hasattr(page, 'update_async') else page.update()
        debug_print("页面已更新")

        # Start periodic tasks in the background
        debug_print("启动周期性任务...")
        page.run_task(app.start_periodic_tasks)
        
        # Start scraping in the background
        debug_print("启动爬虫任务...")
        page.run_task(app.start_scraping)
        
        # Log that scraping has been initiated
        print("🎬 Scraping process has been started in the background")
        debug_print("后台任务已启动")
        
        # Setup window and UI
        setup_window(page, app, False)
    
    # Load the main application with the page
    debug_print("加载主应用...")
    await load_app(page, app)
    debug_print("main() 函数执行完成")


async def load_app(page: ft.Page, app: App):
    """Initialize and load the main application UI"""
    debug_print("=" * 60)
    debug_print("📦 load_app() 函数开始执行")
    debug_print("=" * 60)
    
    is_web = getattr(args, 'web', False) or os.getenv("PLATFORM") == "web"
    login_required = False
    debug_print(f"Web模式: {is_web}, 需要登录: {login_required}")

    # Setup responsive layout based on mode
    debug_print("设置响应式布局...")
    setup_responsive_layout(page, app)
    debug_print("响应式布局设置完成")
    
    # Initialize UI components
    save_progress_overlay = None
    
    # Set up event handlers
    page.on_resize = handle_page_resize(page, app)
    page.on_close = handle_window_event(page, app, save_progress_overlay)
    page.on_disconnect = handle_disconnect(page, app)
    page.on_route_change = handle_route_change(page, app)
    page.window.prevent_close = True
    debug_print("事件处理器设置完成")
    
    if not is_web:
        try:
            debug_print("初始化系统托盘...")
            app.tray_manager = TrayManager(app)
            logger.info("Tray manager initialized successfully")
            debug_print("系统托盘初始化成功")
        except Exception as e:
            logger.error(f"Failed to initialize tray manager: {e}")
            debug_print(f"系统托盘初始化失败: {e}", "ERROR")
    
    # Set theme
    theme_mode = app.settings.user_config.get("theme_mode", "light")
    page.theme_mode = ft.ThemeMode.DARK if theme_mode == "dark" else ft.ThemeMode.LIGHT
    debug_print(f"主题模式: {page.theme_mode}")
    
    # Add save progress overlay
    save_progress_overlay = SaveProgressOverlay(app)
    page.overlay.append(save_progress_overlay.overlay)
    debug_print("保存进度覆盖层已添加")
    
    async def load_app():
        """Initialize and load the main application UI"""
        debug_print("=" * 60)
        debug_print("🔄 内部 load_app() 开始执行")
        debug_print("=" * 60)
        
        if is_web:
            debug_print("Web模式: 设置事件处理器")
            page.on_resize = handle_page_resize(page, app)
            page.on_disconnect = handle_disconnect(page, app)

        # Only add complete_page if it hasn't been added yet
        page_has_controls = len(page.controls) > 0 if hasattr(page, 'controls') else False
        debug_print(f"页面已有控件: {page_has_controls}")
        debug_print(f"是否添加 complete_page: {is_web or not page_has_controls}")
        
        if is_web or not page_has_controls:
            debug_print("添加 complete_page 到页面")
            page.add(app.complete_page)
        
        # Setup event handlers
        page.on_route_change = handle_route_change(page, app)
        page.window.prevent_close = True
        page.window.on_event = handle_window_event(page, app, save_progress_overlay)
        debug_print("事件处理器重新设置完成")
        
        # Start background tasks (only for web mode)
        global global_state
        debug_print(f"Web模式: {is_web}, 周期性任务已启动: {global_state.periodic_tasks_started}")
        
        if is_web:
            if not global_state.periodic_tasks_started:
                global_state.periodic_tasks_started = True
                logger.info("Starting periodic tasks for the first time in web mode")
                debug_print("首次启动周期性任务和爬虫")
                page.run_task(app.start_periodic_tasks)
                page.run_task(app.start_scraping)
            else:
                logger.info("Periodic tasks already running in web mode, skipping initialization")
                debug_print("周期性任务已在运行，跳过初始化")

        page.update()
        debug_print("页面已更新")

        # Handle initial routing
        if page.route == '/':
            last_route = app.settings.user_config.get("last_route", "/home")
            logger.info(f"Restored last route: {last_route}")
            debug_print(f"恢复上次路由: {last_route}")
            page.go(last_route)
        else:
            debug_print(f"使用当前路由: {page.route}")
            page.go(page.route)
        
        debug_print("内部 load_app() 执行完成")

    # Initialize authentication
    if is_web or login_required:
        debug_print("初始化认证模块...")
        auth_manager = AuthManager(app)
        app.auth_manager = auth_manager
        await auth_manager.initialize()
        debug_print("认证模块初始化完成")
        
        if login_required:
            debug_print("需要登录验证")
            session_token = await page.client_storage.get_async("session_token")
            debug_print(f"会话令牌: {session_token}")
            if not session_token or not app.auth_manager.validate_session(session_token):
                debug_print("会话无效，显示登录页面")
                async def on_login_success(token):
                    _session_info = app.auth_manager.active_sessions.get(token, {})
                    app.current_username = _session_info.get("username", "user")
                    debug_print(f"登录成功: {app.current_username}")
                    page.clean()
                    await load_app()
                
                page.clean()
                login_page = LoginPage(page, app.auth_manager, on_login_success)
                page.add(login_page.get_view())
                return
            else:
                session_info = app.auth_manager.active_sessions.get(session_token, {})
                app.current_username = session_info.get("username", "user")
                debug_print(f"会话有效: {app.current_username}")
    else:
        app.current_username = "admin"
        debug_print("无需登录，使用默认用户: admin")
    
    # Load the main application
    debug_print("加载主应用...")
    await load_app()
    debug_print("load_app() 函数执行完成")


async def init_db():
    """Initialize the database and create tables"""
    debug_print("初始化数据库...")
    from app.db.base import create_tables
    logger.info("Initializing database...")
    
    # 检查数据库文件
    db_path = Path("streamcap.db")
    if db_path.exists():
        debug_print(f"数据库文件存在: {db_path} ({db_path.stat().st_size} 字节)")
    else:
        debug_print(f"数据库文件不存在: {db_path}")
    
    await create_tables()
    
    # 验证表是否创建成功
    try:
        import sqlite3
        conn = sqlite3.connect('streamcap.db')
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        debug_print(f"数据库中的表: {[t[0] for t in tables]}")
        conn.close()
    except Exception as e:
        debug_print(f"验证数据库失败: {e}", "ERROR")
    
    logger.info("Database initialized successfully")
    debug_print("数据库初始化完成")

if __name__ == "__main__":
    debug_print("=" * 80)
    debug_print("🚀 StreamCap 启动")
    debug_print("=" * 80)
    
    load_dotenv()
    debug_print(".env 文件已加载")
    
    # 检查环境变量
    debug_print(f"DOUYIN_COOKIE: {'已设置' if os.getenv('DOUYIN_COOKIE') else '未设置'}")
    debug_print(f"PLATFORM: {os.getenv('PLATFORM')}")
    debug_print(f"HOST: {os.getenv('HOST', DEFAULT_HOST)}")
    debug_print(f"PORT: {os.getenv('PORT', DEFAULT_PORT)}")
    
    platform = os.getenv("PLATFORM")
    default_host = os.getenv("HOST", DEFAULT_HOST)
    default_port = int(os.getenv("PORT", DEFAULT_PORT))
    
    # Initialize database before starting the app
    import asyncio
    debug_print("运行数据库初始化...")
    asyncio.run(init_db())
    debug_print("数据库初始化完成")

    parser = argparse.ArgumentParser(description="Run the Flet app with optional web mode.")
    parser.add_argument("--web", action="store_true", help="Run the app in web mode")
    parser.add_argument("--host", type=str, default=default_host, help=f"Host address (default: {default_host})")
    parser.add_argument("--port", type=int, default=default_port, help=f"Port number (default: {default_port})")
    args = parser.parse_args()
    
    debug_print(f"命令行参数: web={args.web}, host={args.host}, port={args.port}")

    if args.web or platform == "web":
        logger.debug("Running in web mode on http://" + args.host + ":" + str(args.port))
        debug_print(f"以 Web 模式启动: http://{args.host}:{args.port}")
        debug_print("=" * 80)
        
        ft.app(
            target=main,
            view=ft.AppView.WEB_BROWSER,
            host=args.host,
            port=args.port,
            assets_dir=ASSETS_DIR,
            web_renderer=ft.WebRenderer.CANVAS_KIT
        )

    else:
        debug_print("以桌面模式启动")
        debug_print("=" * 80)
        ft.app(target=main, assets_dir=ASSETS_DIR)
    
    debug_print("程序结束")