"""
日记系统命令
提供临时性命令用于测试和调试
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
    """日记命令基类，包含所有日记相关子命令"""

    command_name: str = "diary"
    command_description: str = "连续日记系统管理命令"
    command_aliases: ClassVar[list[str]] = ["日记"]
    command_usage = "/diary <子命令> - 使用 /diary help 查看详细帮助"

    # 从插件注入
    manager: ClassVar["DiaryManager | None"] = None

    @require_permission("plugin.continuous_diary_memory.command.use")
    async def execute(self, args: CommandArgs) -> tuple[bool, str, bool]:
        """执行日记命令"""
        if not self.manager:
            await self.send_text("❌ 日记管理器未初始化")
            return False, "管理器未初始化", True

        all_args = args.get_args()
        if not all_args:
            await self.send_text("请使用 /diary help 查看帮助信息")
            return True, "显示提示", True

        subcommand = all_args[0].lower()

        # 获取会话信息
        is_group = self.message.group_info is not None
        conversation_id = (
            self.message.group_info.group_id  # type: ignore
            if is_group
            else self.message.user_info.user_id
        )
        chat_type = "group" if is_group else "private"

        try:
            if subcommand == "help":
                return await self._cmd_help()
            elif subcommand == "summary":
                return await self._cmd_summary(conversation_id, chat_type)
            elif subcommand == "consolidate":
                return await self._cmd_consolidate(conversation_id, chat_type)
            elif subcommand == "show":
                return await self._cmd_show(conversation_id)
            elif subcommand == "pending":
                return await self._cmd_pending(conversation_id)
            else:
                await self.send_text(
                    f"❓ 未知子命令：{subcommand}\n使用 /diary help 查看可用命令"
                )
                return False, f"未知子命令: {subcommand}", True

        except Exception as e:
            logger.error(f"[DiaryCommand] 执行命令失败: {e}", exc_info=True)
            await self.send_text(f"❌ 命令执行失败：{str(e)}")
            return False, "命令执行异常", True

    async def _cmd_help(self) -> tuple[bool, str, bool]:
        """显示帮助信息"""
        help_text = """📖 连续日记命令帮助

可用命令：
• /diary summary - 强制触发今天的增量总结
• /diary consolidate - 强制触发日终总结（模拟跨天）
• /diary show - 查看当前日记内容
• /diary pending - 查看待处理消息数
• /diary help - 显示此帮助信息

说明：
- 这些命令仅用于测试和调试
- 增量总结会清空pending消息
- 日终总结会将今天的内容归档到昨天"""

        await self.send_text(help_text)
        return True, "显示帮助", True

    async def _cmd_summary(
        self, conversation_id: str, chat_type: str
    ) -> tuple[bool, str, bool]:
        """强制触发增量总结"""
        logger.info(f"[DiaryCommand] 收到强制总结命令: {conversation_id}")
        
        # 通过群号/用户ID获取实际的stream_id
        from src.plugin_system.apis import chat_api
        
        if chat_type == "group":
            stream = chat_api.get_stream_by_group_id(conversation_id)
        else:
            stream = chat_api.get_stream_by_user_id(conversation_id)
        
        if not stream:
            await self.send_text(f"❌ 未找到对应的聊天流")
            return False, "聊天流不存在", True
        
        stream_id = stream.stream_id
        logger.info(f"[DiaryCommand] 群号{conversation_id} -> stream_id: {stream_id[:16]}...")

        # 构建完整人设
        from src.config.config import global_config

        identity_parts = []
        if global_config and global_config.personality:
            if global_config.personality.personality_core:
                identity_parts.append(
                    f"核心人格：{global_config.personality.personality_core}"
                )
            if global_config.personality.personality_side:
                identity_parts.append(
                    f"性格侧面：{global_config.personality.personality_side}"
                )
            if global_config.personality.identity:
                identity_parts.append(f"身份特征：{global_config.personality.identity}")
            if global_config.personality.reply_style:
                identity_parts.append(f"表达方式：{global_config.personality.reply_style}")

        identity = "\n".join(identity_parts) if identity_parts else "一个友善的对话伙伴"

        success = await self.manager.trigger_summary(stream_id, identity, chat_type)  # type: ignore

        if success:
            await self.send_text("✅ 已生成今天的增量总结")
        else:
            await self.send_text("❌ 总结失败（可能没有待处理消息）")

        return success, "强制总结完成" if success else "总结失败", True

    async def _cmd_consolidate(
        self, conversation_id: str, chat_type: str
    ) -> tuple[bool, str, bool]:
        """强制触发日终总结（模拟跨天）"""
        logger.info(f"[DiaryCommand] 收到强制日终总结命令: {conversation_id}")
        
        # 通过群号/用户ID获取实际的stream_id
        from src.plugin_system.apis import chat_api
        
        if chat_type == "group":
            stream = chat_api.get_stream_by_group_id(conversation_id)
        else:
            stream = chat_api.get_stream_by_user_id(conversation_id)
        
        if not stream:
            await self.send_text(f"❌ 未找到对应的聊天流")
            return False, "聊天流不存在", True
        
        stream_id = stream.stream_id

        try:
            # 直接调用内部方法（模拟跨天）
            async with self.manager._get_lock(stream_id):  # type: ignore
                conv_data = await self.manager._load_conversation(stream_id)  # type: ignore

                # 临时修改日期标记触发跨天检测
                yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                conv_data["last_summary_date"] = yesterday

                await self.manager._save_conversation(stream_id, conv_data)  # type: ignore

            # 触发跨天检测
            await self.manager._check_and_do_daily_summary(conv_data, stream_id, chat_type)  # type: ignore

            await self.send_text("✅ 已强制执行日终总结")
            return True, "日终总结完成", True

        except Exception as e:
            logger.error(f"[DiaryCommand] 强制日终总结失败: {e}", exc_info=True)
            await self.send_text(f"❌ 日终总结失败：{str(e)}")
            return False, "日终总结失败", True

    async def _cmd_show(self, conversation_id: str) -> tuple[bool, str, bool]:
        """显示当前日记内容"""
        logger.info(f"[DiaryCommand] 收到查看日记命令: {conversation_id}")
        
        # 通过群号/用户ID获取实际的stream_id
        from src.plugin_system.apis import chat_api
        
        is_group = self.message.group_info is not None
        if is_group:
            stream = chat_api.get_stream_by_group_id(conversation_id)
        else:
            stream = chat_api.get_stream_by_user_id(conversation_id)
        
        if not stream:
            await self.send_text(f"❌ 未找到对应的聊天流")
            return False, "聊天流不存在", True
        
        stream_id = stream.stream_id

        diary_content = await self.manager.get_diary_for_prompt(stream_id)  # type: ignore

        if diary_content:
            await self.send_text(f"📖 当前日记内容：\n\n{diary_content}")
        else:
            await self.send_text("📖 当前还没有日记内容")

        return True, "显示日记内容", True

    async def _cmd_pending(self, conversation_id: str) -> tuple[bool, str, bool]:
        """查看待处理消息数"""
        logger.info(f"[DiaryCommand] 收到查看pending命令: {conversation_id}")
        
        # 通过群号/用户ID获取实际的stream_id
        from src.plugin_system.apis import chat_api
        
        is_group = self.message.group_info is not None
        if is_group:
            stream = chat_api.get_stream_by_group_id(conversation_id)
        else:
            stream = chat_api.get_stream_by_user_id(conversation_id)
        
        if not stream:
            await self.send_text(f"❌ 未找到对应的聊天流")
            return False, "聊天流不存在", True
        
        stream_id = stream.stream_id

        pending_count = await self.manager.get_pending_count(stream_id)  # type: ignore

        await self.send_text(f"📊 当前待处理消息数：{pending_count}")

        return True, "显示待处理消息数", True
