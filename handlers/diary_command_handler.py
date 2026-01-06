"""
日记命令处理器
提供临时性命令用于测试和调试
"""

from typing import Any, ClassVar, TYPE_CHECKING, Optional

from src.plugin_system import BaseEventHandler, EventType
from src.plugin_system.base.base_event import HandlerResult
from src.common.logger import get_logger

if TYPE_CHECKING:
    from ..core.diary_manager import DiaryManager

logger = get_logger("continuous_diary.command")


class DiaryCommandHandler(BaseEventHandler):
    """日记命令处理器"""

    handler_name = "diary_command_handler"
    handler_description = "处理日记相关的临时性命令"

    # 监听消息接收事件
    init_subscribe: ClassVar[list[EventType]] = [EventType.ON_MESSAGE]

    manager: "DiaryManager | None" = None  # 从插件注入

    async def execute(self, params: dict) -> HandlerResult:
        """处理命令"""

        if not self.manager:
            logger.warning("[DiaryCommand] DiaryManager 未初始化")
            return HandlerResult(success=False, continue_process=True)

        # 提取消息信息
        message = params.get("message")
        if not message:
            return HandlerResult(success=True, continue_process=True)

        # 使用属性访问而不是字典方法（message可能是DatabaseMessages对象）
        content = getattr(message, "content", "") or ""
        content = content.strip()
        
        # 检查是否是日记命令
        if not content.startswith("/diary"):
            return HandlerResult(success=True, continue_process=True)

        # 解析命令
        parts = content.split()
        command = parts[0]

        conversation_id = params.get("conversation_id")
        if not conversation_id:
            return HandlerResult(success=True, continue_process=True)
        
        chat_type = "group" if params.get("is_group_chat", False) else "private"

        try:
            # /diary_summary - 强制触发增量总结
            if command == "/diary_summary":
                logger.info(f"[DiaryCommand] 收到强制总结命令: {conversation_id}")
                
                # 构建完整人设
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
                
                identity = "\n".join(identity_parts) if identity_parts else "一个友善的对话伙伴"
                
                success = await self.manager.trigger_summary(conversation_id, identity, chat_type)
                
                if success:
                    response = "✅ 已生成今天的增量总结"
                else:
                    response = "❌ 总结失败（可能没有待处理消息）"
                
                # 返回响应消息
                return HandlerResult(
                    success=True,
                    continue_process=False,  # 阻止继续处理
                    message=response
                )

            # /diary_consolidate - 强制触发日终总结
            elif command == "/diary_consolidate":
                logger.info(f"[DiaryCommand] 收到强制日终总结命令: {conversation_id}")
                
                # 手动触发跨天总结
                response = await self._force_daily_consolidate(conversation_id, chat_type)
                
                return HandlerResult(
                    success=True,
                    continue_process=False,
                    message=response
                )

            # /diary_show - 显示当前日记内容
            elif command == "/diary_show":
                logger.info(f"[DiaryCommand] 收到查看日记命令: {conversation_id}")
                
                diary_content = await self.manager.get_diary_for_prompt(conversation_id)
                
                if diary_content:
                    response = f"📖 当前日记内容：\n\n{diary_content}"
                else:
                    response = "📖 当前还没有日记内容"
                
                return HandlerResult(
                    success=True,
                    continue_process=False,
                    message=response
                )

            # /diary_pending - 查看待处理消息数
            elif command == "/diary_pending":
                logger.info(f"[DiaryCommand] 收到查看pending命令: {conversation_id}")
                
                pending_count = await self.manager.get_pending_count(conversation_id)
                
                response = f"📊 当前待处理消息数：{pending_count}"
                
                return HandlerResult(
                    success=True,
                    continue_process=False,
                    message=response
                )

            # /diary_help - 显示帮助信息
            elif command == "/diary_help":
                response = """📖 连续日记命令帮助

可用命令：
• /diary_summary - 强制触发今天的增量总结
• /diary_consolidate - 强制触发日终总结（模拟跨天）
• /diary_show - 查看当前日记内容
• /diary_pending - 查看待处理消息数
• /diary_help - 显示此帮助信息

说明：
- 这些命令仅用于测试和调试
- 增量总结会清空pending消息
- 日终总结会将今天的内容归档到昨天"""
                
                return HandlerResult(
                    success=True,
                    continue_process=False,
                    message=response
                )

            else:
                response = f"❓ 未知命令：{command}\n使用 /diary_help 查看可用命令"
                return HandlerResult(
                    success=True,
                    continue_process=False,
                    message=response
                )

        except Exception as e:
            logger.error(f"[DiaryCommand] 处理命令失败: {e}", exc_info=True)
            return HandlerResult(
                success=False,
                continue_process=False,
                message=f"❌ 命令执行失败：{str(e)}"
            )

    async def _force_daily_consolidate(self, conversation_id: str, chat_type: str) -> str:
        """强制执行日终总结"""
        if not self.manager:
            return "❌ DiaryManager 未初始化"
        
        try:
            # 直接调用内部方法（模拟跨天）
            # type: ignore 用于忽略私有方法的类型检查
            async with self.manager._get_lock(conversation_id):  # type: ignore
                conv_data = await self.manager._load_conversation(conversation_id)  # type: ignore
                
                # 临时修改日期标记触发跨天检测
                from datetime import datetime, timedelta
                yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                conv_data["last_summary_date"] = yesterday
                
                await self.manager._save_conversation(conversation_id, conv_data)  # type: ignore
            
            # 触发跨天检测
            await self.manager._check_and_do_daily_summary(conv_data, conversation_id, chat_type)  # type: ignore
            
            return "✅ 已强制执行日终总结"
        
        except Exception as e:
            logger.error(f"[DiaryCommand] 强制日终总结失败: {e}", exc_info=True)
            return f"❌ 日终总结失败：{str(e)}"
