"""
TG Export - Telegram Bot
处理 Telegram Bot 命令
"""
import asyncio
from typing import Optional
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BotCommand

from ..config import settings
from ..models import ExportOptions, ExportFormat, TaskStatus
from .client import telegram_client
from .exporter import export_manager


class TelegramBot:
    """Telegram Bot 处理器"""
    
    def __init__(self):
        self._bot: Optional[Client] = None
        self._user_states = {}  # 用户状态管理
    
    async def init(self, bot_token: str, api_id: int, api_hash: str):
        """初始化 Bot"""
        self._bot = Client(
            name="tg_export_bot",
            api_id=api_id,
            api_hash=api_hash,
            bot_token=bot_token,
            workdir=str(settings.SESSIONS_DIR)
        )
        self._register_handlers()
    
    def _register_handlers(self):
        """注册消息处理器"""
        
        @self._bot.on_message(filters.command("start"))
        async def start_handler(client: Client, message: Message):
            await self._handle_start(message)
        
        @self._bot.on_message(filters.command("help"))
        async def help_handler(client: Client, message: Message):
            await self._handle_help(message)
        
        @self._bot.on_message(filters.command("status"))
        async def status_handler(client: Client, message: Message):
            await self._handle_status(message)
        
        @self._bot.on_message(filters.command("list"))
        async def list_handler(client: Client, message: Message):
            await self._handle_list(message)
        
        @self._bot.on_message(filters.command("export"))
        async def export_handler(client: Client, message: Message):
            await self._handle_export(message)
        
        @self._bot.on_message(filters.command("tasks"))
        async def tasks_handler(client: Client, message: Message):
            await self._handle_tasks(message)
        
        @self._bot.on_message(filters.command("cancel"))
        async def cancel_handler(client: Client, message: Message):
            await self._handle_cancel(message)
        
        @self._bot.on_message(filters.command("pause"))
        async def pause_handler(client: Client, message: Message):
            await self._handle_pause(message)
        
        @self._bot.on_message(filters.command("resume"))
        async def resume_handler(client: Client, message: Message):
            await self._handle_resume(message)
        
        @self._bot.on_message(filters.command("retry"))
        async def retry_handler(client: Client, message: Message):
            await self._handle_retry(message)
        
        @self._bot.on_message(filters.command("failed"))
        async def failed_handler(client: Client, message: Message):
            await self._handle_failed(message)
        
        @self._bot.on_callback_query()
        async def callback_handler(client: Client, callback: CallbackQuery):
            await self._handle_callback(callback)
    
    async def start(self):
        """启动 Bot"""
        if self._bot:
            await self._bot.start()
            # 注册命令菜单
            await self._bot.set_bot_commands([
                BotCommand("start", "显示欢迎信息"),
                BotCommand("help", "查看详细帮助"),
                BotCommand("status", "查看连接状态"),
                BotCommand("list", "列出所有对话"),
                BotCommand("export", "开始导出"),
                BotCommand("tasks", "查看任务列表"),
                BotCommand("pause", "暂停任务"),
                BotCommand("resume", "恢复任务"),
                BotCommand("cancel", "取消任务"),
                BotCommand("failed", "查看失败下载"),
                BotCommand("retry", "重试失败下载"),
            ])
            print("✅ TG Export Bot 已启动，命令菜单已注册")
    
    async def stop(self):
        """停止 Bot"""
        if self._bot:
            await self._bot.stop()
    
    async def _handle_start(self, message: Message):
        """处理 /start 命令"""
        welcome_text = """
🎉 **欢迎使用 TG Export Bot!**

Telegram 全功能导出工具，支持：
• 🔒 私密频道/群组/私聊导出
• 📷 图片/视频/文件/语音下载
• 📄 HTML + JSON 双格式输出
• ♾️ 无文件大小限制
• 🔄 断点续传支持
• 🎯 消息范围筛选 (1-100)

**📝 命令列表:**
`/start` - 显示此欢迎信息
`/help` - 查看详细帮助
`/status` - 查看连接状态
`/list` - 列出所有对话
`/export` - 开始导出向导
`/export <ID>` - 导出指定聊天
`/export <ID> 1-100` - 导出指定消息范围
`/tasks` - 查看任务列表
`/pause` `/resume` `/cancel` - 任务控制
`/failed` `/retry` - 失败处理

👉 点击下方按钮快速开始
        """
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 列出聊天", callback_data="list"),
                InlineKeyboardButton("📥 开始导出", callback_data="export_menu")
            ],
            [
                InlineKeyboardButton("📊 查看任务", callback_data="tasks"),
                InlineKeyboardButton("❓ 帮助", callback_data="help")
            ],
            [
                InlineKeyboardButton("🔗 连接状态", callback_data="status")
            ]
        ])
        
        await message.reply(welcome_text, reply_markup=keyboard)
    
    async def _handle_help(self, message: Message):
        """处理 /help 命令"""
        help_text = """
📖 **TG Export Bot 命令手册**

━━━━━ **基础命令** ━━━━━
`/start` - 显示欢迎信息和快捷按钮
`/help` - 显示此帮助文档
`/status` - 查看 Telegram 账号连接状态

━━━━━ **导出命令** ━━━━━
`/list` - 列出所有可导出的对话 (私聊/群组/频道)
`/export` - 打开导出向导菜单
`/export <chat_id>` - 导出指定聊天的全部消息
`/export <chat_id> 1-100` - 导出指定聊天的第1-100条消息
`/export <chat_id> 1-0` - 导出指定聊天的全部消息 (0=最新)

━━━━━ **任务管理** ━━━━━
`/tasks` - 查看所有导出任务及进度
`/pause <task_id>` - 暂停指定任务
`/resume <task_id>` - 恢复暂停的任务
`/cancel <task_id>` - 取消指定任务
`/failed <task_id>` - 查看失败的下载列表
`/retry <task_id>` - 重试失败的下载

━━━━━ **导出选项** ━━━━━
📤 **聊天类型:**
  • 私聊 / 机器人
  • 私密群组 / 公开群组
  • 私密频道 / 公开频道

🎨 **媒体类型:**
  • 🖼 图片 / 🎬 视频 / 🎤 语音
  • 📎 文件 / 🎨 贴纸 / 🎬 GIF

⚙️ **高级功能:**
  • 消息范围筛选 (1-100)
  • 断点续传
  • 跳过已下载文件
  • HTML/JSON 双格式输出

💡 **示例:**
`/export -1001234567890` - 导出该频道全部
`/export -1001234567890 1-50` - 导出前50条消息
        """
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🏠 返回主菜单", callback_data="start")
            ]
        ])
        await message.reply(help_text, reply_markup=keyboard)
    
    async def _handle_status(self, message: Message):
        """处理 /status 命令"""
        if telegram_client.is_authorized:
            me = await telegram_client.get_me()
            status_text = f"""
✅ **Telegram 已连接**

👤 用户: {me.get('first_name', '')} {me.get('last_name', '')}
📱 用户名: @{me.get('username', 'N/A')}
🆔 ID: {me.get('id', 'N/A')}
            """
        else:
            status_text = """
❌ **Telegram 未连接**

请在 Web 面板中完成登录验证。
            """
        await message.reply(status_text)
    
    async def _handle_list(self, message: Message):
        """处理 /list 命令"""
        if not telegram_client.is_authorized:
            await message.reply("❌ 请先登录 Telegram")
            return
        
        await message.reply("⏳ 正在获取对话列表...")
        
        dialogs = await telegram_client.get_dialogs()
        
        if not dialogs:
            await message.reply("📭 没有找到任何对话")
            return
        
        # 按类型分组
        private = [d for d in dialogs if d.type.value == "private"]
        groups = [d for d in dialogs if d.type.value in ["group", "supergroup"]]
        channels = [d for d in dialogs if d.type.value == "channel"]
        
        text = f"📋 **对话列表** (共 {len(dialogs)} 个)\n\n"
        
        if private:
            text += f"👤 **私聊** ({len(private)})\n"
            for d in private[:5]:
                text += f"  • {d.title} (`{d.id}`)\n"
            if len(private) > 5:
                text += f"  ... 还有 {len(private) - 5} 个\n"
            text += "\n"
        
        if groups:
            text += f"👥 **群组** ({len(groups)})\n"
            for d in groups[:5]:
                text += f"  • {d.title} (`{d.id}`)\n"
            if len(groups) > 5:
                text += f"  ... 还有 {len(groups) - 5} 个\n"
            text += "\n"
        
        if channels:
            text += f"📢 **频道** ({len(channels)})\n"
            for d in channels[:5]:
                text += f"  • {d.title} (`{d.id}`)\n"
            if len(channels) > 5:
                text += f"  ... 还有 {len(channels) - 5} 个\n"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 导出全部", callback_data="export_all")],
            [InlineKeyboardButton("🎯 选择导出", callback_data="export_menu")]
        ])
        
        await message.reply(text, reply_markup=keyboard)
    
    async def _handle_export(self, message: Message):
        """处理 /export 命令"""
        if not telegram_client.is_authorized:
            await message.reply("❌ 请先登录 Telegram")
            return
        
        # 解析参数
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        
        if args:
            # 直接导出指定聊天
            try:
                chat_id = int(args[0])
                await self._start_export([chat_id], message)
            except ValueError:
                await message.reply("❌ 无效的聊天 ID")
        else:
            # 显示导出菜单
            await self._show_export_menu(message)
    
    async def _show_export_menu(self, message: Message):
        """显示导出菜单"""
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📥 导出全部", callback_data="export_all"),
            ],
            [
                InlineKeyboardButton("👤 仅私聊", callback_data="export_private"),
                InlineKeyboardButton("👥 仅群组", callback_data="export_groups"),
            ],
            [
                InlineKeyboardButton("📢 仅频道", callback_data="export_channels"),
                InlineKeyboardButton("🔒 仅私密", callback_data="export_private_only"),
            ],
            [
                InlineKeyboardButton("⚙️ 高级选项", callback_data="export_advanced"),
            ]
        ])
        
        await message.reply(
            "📥 **选择导出范围**\n\n请选择要导出的内容类型：",
            reply_markup=keyboard
        )
    
    async def _handle_tasks(self, message: Message):
        """处理 /tasks 命令"""
        tasks = export_manager.get_all_tasks()
        
        if not tasks:
            await message.reply("📭 没有导出任务")
            return
        
        text = "📊 **导出任务列表**\n\n"
        
        for task in tasks[-10:]:  # 最近 10 个
            status_emoji = {
                TaskStatus.PENDING: "⏳",
                TaskStatus.RUNNING: "🔄",
                TaskStatus.COMPLETED: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.CANCELLED: "🚫"
            }
            emoji = status_emoji.get(task.status, "❓")
            
            text += f"{emoji} **{task.name}**\n"
            text += f"   状态: {task.status.value}\n"
            if task.status == TaskStatus.RUNNING:
                text += f"   进度: {task.progress:.1f}%\n"
            text += f"   ID: `{task.id[:8]}...`\n\n"
        
        await message.reply(text)
    
    async def _handle_cancel(self, message: Message):
        """处理 /cancel 命令"""
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        
        if not args:
            await message.reply("用法: /cancel <task_id>")
            return
        
        task_id = args[0]
        success = await export_manager.cancel_export(task_id)
        
        if success:
            await message.reply(f"✅ 任务已取消: {task_id[:8]}...")
        else:
            await message.reply("❌ 取消失败，任务不存在或已完成")
    
    async def _handle_pause(self, message: Message):
        """处理 /pause 命令"""
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        
        if not args:
            await message.reply("用法: /pause <task_id>")
            return
        
        task_id = args[0]
        task = export_manager.get_task(task_id)
        
        if not task:
            await message.reply("❌ 任务不存在")
            return
        
        if task.status != TaskStatus.RUNNING:
            await message.reply(f"❌ 任务状态为 {task.status.value}，无法暂停")
            return
        
        export_manager.pause_export(task_id)
        await message.reply(f"⏸ 任务已暂停: {task_id[:8]}...")
    
    async def _handle_resume(self, message: Message):
        """处理 /resume 命令"""
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        
        if not args:
            await message.reply("用法: /resume <task_id>")
            return
        
        task_id = args[0]
        task = export_manager.get_task(task_id)
        
        if not task:
            await message.reply("❌ 任务不存在")
            return
        
        if task.status != TaskStatus.PAUSED:
            await message.reply(f"❌ 任务状态为 {task.status.value}，无法恢复")
            return
        
        export_manager.resume_export(task_id)
        await message.reply(f"▶ 任务已恢复: {task_id[:8]}...")
    
    async def _handle_retry(self, message: Message):
        """处理 /retry 命令"""
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        
        if not args:
            await message.reply("用法: /retry <task_id>")
            return
        
        task_id = args[0]
        task = export_manager.get_task(task_id)
        
        if not task:
            await message.reply("❌ 任务不存在")
            return
        
        if not task.failed_downloads:
            await message.reply("✅ 没有失败的下载需要重试")
            return
        
        count = len(task.failed_downloads)
        # 标记为待重试
        for fail in task.failed_downloads:
            fail.resolved = False
        
        await message.reply(f"🔄 已标记 {count} 个失败下载待重试\n使用 /resume {task_id[:8]} 开始重试")
    
    async def _handle_failed(self, message: Message):
        """处理 /failed 命令"""
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        
        if not args:
            # 显示所有任务的失败统计
            tasks = export_manager.get_all_tasks()
            failed_tasks = [t for t in tasks if t.failed_downloads]
            
            if not failed_tasks:
                await message.reply("✅ 没有失败的下载")
                return
            
            text = "⚠️ **失败下载统计**\n\n"
            for t in failed_tasks[:10]:
                text += f"• {t.name}: {len(t.failed_downloads)} 个失败\n"
                text += f"  ID: `{t.id[:8]}...`\n\n"
            
            text += "使用 /failed <task_id> 查看详情"
            await message.reply(text)
            return
        
        task_id = args[0]
        task = export_manager.get_task(task_id)
        
        if not task:
            await message.reply("❌ 任务不存在")
            return
        
        if not task.failed_downloads:
            await message.reply("✅ 该任务没有失败的下载")
            return
        
        text = f"⚠️ **失败下载列表** ({len(task.failed_downloads)} 个)\n\n"
        for fail in task.failed_downloads[:20]:
            text += f"• 消息 #{fail.message_id}\n"
            if fail.file_name:
                text += f"  文件: {fail.file_name[:30]}...\n" if len(fail.file_name) > 30 else f"  文件: {fail.file_name}\n"
            text += f"  错误: {fail.error_type}\n\n"
        
        if len(task.failed_downloads) > 20:
            text += f"... 还有 {len(task.failed_downloads) - 20} 个\n"
        
        text += f"\n使用 /retry {task_id[:8]} 重试全部"
        await message.reply(text)
    
    async def _handle_callback(self, callback: CallbackQuery):
        """处理回调查询"""
        data = callback.data
        
        if data == "start":
            await callback.answer()
            await self._handle_start(callback.message)
        
        elif data == "list":
            await callback.answer()
            await self._handle_list(callback.message)
        
        elif data == "help":
            await callback.answer()
            await self._handle_help(callback.message)
        
        elif data == "status":
            await callback.answer()
            await self._handle_status(callback.message)
        
        elif data == "tasks":
            await callback.answer()
            await self._handle_tasks(callback.message)
        
        elif data == "export_menu":
            await callback.answer()
            await self._show_export_menu(callback.message)
        
        elif data == "export_all":
            await callback.answer("开始导出全部...")
            await self._start_export([], callback.message, export_all=True)
        
        elif data == "export_private":
            await callback.answer("开始导出私聊...")
            options = ExportOptions(
                private_chats=True, bot_chats=False,
                private_groups=False, private_channels=False,
                public_groups=False, public_channels=False
            )
            await self._start_export_with_options(options, callback.message, "私聊导出")
        
        elif data == "export_groups":
            await callback.answer("开始导出群组...")
            options = ExportOptions(
                private_chats=False, bot_chats=False,
                private_groups=True, private_channels=False,
                public_groups=True, public_channels=False
            )
            await self._start_export_with_options(options, callback.message, "群组导出")
        
        elif data == "export_channels":
            await callback.answer("开始导出频道...")
            options = ExportOptions(
                private_chats=False, bot_chats=False,
                private_groups=False, private_channels=True,
                public_groups=False, public_channels=True
            )
            await self._start_export_with_options(options, callback.message, "频道导出")
        
        else:
            await callback.answer("功能开发中...")
    
    async def _start_export(self, chat_ids: list, message: Message, export_all: bool = False):
        """启动导出"""
        options = ExportOptions(
            specific_chats=chat_ids if chat_ids else [],
            export_format=ExportFormat.BOTH
        )
        
        if export_all:
            options.private_chats = True
            options.private_groups = True
            options.private_channels = True
        
        await self._start_export_with_options(options, message, "全量导出")
    
    async def _start_export_with_options(self, options: ExportOptions, message: Message, name: str):
        """使用指定选项启动导出"""
        task = export_manager.create_task(name, options)
        
        # 添加进度回调
        async def progress_callback(t):
            if t.status == TaskStatus.COMPLETED:
                await message.reply(f"✅ 导出完成!\n\n📁 位置: {t.options.export_path}")
            elif t.status == TaskStatus.FAILED:
                await message.reply(f"❌ 导出失败: {t.error}")
        
        export_manager.add_progress_callback(task.id, progress_callback)
        
        # 启动任务
        await export_manager.start_export(task.id)
        
        await message.reply(
            f"🚀 **导出任务已启动**\n\n"
            f"任务名: {name}\n"
            f"任务 ID: `{task.id[:8]}...`\n\n"
            f"使用 /tasks 查看进度"
        )


# 全局 Bot 实例
telegram_bot = TelegramBot()
