"""
日记系统命令
精简版：/diary 查看状态，/diary refresh 强制刷新
"""

from datetime import datetime, timedelta
from typing import ClassVar, TYPE_CHECKING

from src.common.logger import get_logger
from src.plugin_system.base.command_args import CommandArgs
from src.plugin_system.base.plus_command import PlusCommand
from src.plugin_system.utils.permission_decorators import require_permission

if TYPE_CHECKING:
    from ..core.diary_manager import DiaryManager

logger = get_logger("continuous_diary.commands")


class DiaryCommand(PlusCommand):
    """日记命令 - 精简版"""

    command_name: str = "diary"
    command_description: str = "查看和管理日记记忆"
    command_aliases: ClassVar[list[str]] = ["日记"]
    command_usage = "/diary [refresh] - 查看状态或刷新日记"

    # 从插件注入
    manager: ClassVar["DiaryManager | None"] = None

    @require_permission("plugin.continuous_diary_memory.command.use")
    async def execute(self, args: CommandArgs) -> tuple[bool, str, bool]:
        """执行日记命令"""
        if not self.manager:
            await self.send_text("❌ 日记管理器未初始化")
            return False, "管理器未初始化", True

        all_args = args.get_args()
        subcommand = all_args[0].lower() if all_args else None

        # 获取会话信息
        stream_id = await self._get_stream_id()
        if not stream_id:
            await self.send_text("❌ 无法获取当前会话信息")
            return False, "会话信息获取失败", True

        try:
            if subcommand == "refresh":
                return await self._cmd_refresh(stream_id)
            else:
                return await self._cmd_status(stream_id)

        except Exception as e:
            logger.error(f"[DiaryCommand] 执行命令失败: {e}", exc_info=True)
            await self.send_text(f"❌ 命令执行失败：{str(e)}")
            return False, "命令执行异常", True

    async def _get_stream_id(self) -> str | None:
        """获取当前会话的 stream_id"""
        from src.plugin_system.apis import chat_api
        
        is_group = self.message.group_info is not None
        
        if is_group:
            group_id = self.message.group_info.group_id  # type: ignore
            stream = chat_api.get_stream_by_group_id(group_id)
        else:
            user_id = self.message.user_info.user_id
            stream = chat_api.get_stream_by_user_id(user_id)
        
        if stream:
            return stream.stream_id
        return None
    
    async def _get_identity(self) -> str:
        """获取 bot 的人设信息"""
        from src.config.config import global_config

        identity_parts = []
        if global_config and global_config.personality:
            if global_config.personality.personality_core:
                identity_parts.append(f"核心人格：{global_config.personality.personality_core}")
            if global_config.personality.personality_side:
                identity_parts.append(f"性格侧面：{global_config.personality.personality_side}")
            if global_config.personality.identity:
                identity_parts.append(f"身份特征：{global_config.personality.identity}")
            if global_config.personality.reply_style:
                identity_parts.append(f"表达方式：{global_config.personality.reply_style}")

        return "\n".join(identity_parts) if identity_parts else "一个友善的对话伙伴"

    async def _cmd_status(self, stream_id: str) -> tuple[bool, str, bool]:
        """显示日记状态"""
        # 获取三天的状态
        today_status = await self.manager.get_summary_status(stream_id, "today")  # type: ignore
        yesterday_status = await self.manager.get_summary_status(stream_id, "yesterday")  # type: ignore
        older_status = await self.manager.get_summary_status(stream_id, "older")  # type: ignore
        
        # 获取待处理消息数
        pending = await self.manager.get_pending_count(stream_id)  # type: ignore
        
        # 格式化日期
        today = datetime.now().strftime("%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%m-%d")
        day_before = (datetime.now() - timedelta(days=2)).strftime("%m-%d")
        
        status_text = f"""📖 日记状态

今天 ({today}): {today_status}
昨天 ({yesterday}): {yesterday_status}
前天 ({day_before}): {older_status}

📝 待处理消息: {pending} 条

💡 使用 /diary refresh 强制刷新所有日记"""
        
        await self.send_text(status_text)
        return True, "显示状态", True

    async def _cmd_refresh(self, stream_id: str) -> tuple[bool, str, bool]:
        """强制刷新三天的日记"""
        await self.send_text("🔄 正在刷新日记，请稍候...")
        
        # 获取人设和对话类型
        identity = await self._get_identity()
        is_group = self.message.group_info is not None
        chat_type = "group" if is_group else "private"
        
        # 刷新所有日期
        success_count, total = await self.manager.refresh_all_dates(  # type: ignore
            stream_id, identity, chat_type
        )
        
        if success_count == total:
            await self.send_text(f"✅ 已刷新全部 {total} 天的日记")
        elif success_count > 0:
            await self.send_text(f"⚠️ 刷新完成 {success_count}/{total} 天（部分日期可能没有消息）")
        else:
            await self.send_text("❌ 刷新失败（可能没有可用的对话记录）")
        
        return success_count > 0, f"刷新完成 {success_count}/{total}", True
