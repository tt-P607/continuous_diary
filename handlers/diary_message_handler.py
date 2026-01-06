"""
消息事件处理器 - 已废弃
日记系统直接从数据库读取消息，不再需要事件处理器
"""

from typing import Any, ClassVar, TYPE_CHECKING

from src.plugin_system import BaseEventHandler, EventType
from src.plugin_system.base.base_event import HandlerResult
from src.common.logger import get_logger

if TYPE_CHECKING:
    from ..core.diary_manager import DiaryManager

logger = get_logger("continuous_diary.handler")


class DiaryMessageHandler(BaseEventHandler):
    """消息事件处理器 - 仅用于定时检查是否需要触发总结"""

    handler_name = "diary_message_handler"
    handler_description = "定时检查是否需要触发日记总结"

    # 监听消息接收事件
    init_subscribe: ClassVar[list[EventType]] = [EventType.ON_MESSAGE]

    manager: ClassVar["DiaryManager | None"] = None  # 从插件注入

    async def execute(self, params: dict) -> HandlerResult:
        """处理消息事件 - 仅检查是否需要触发总结"""

        # 日记系统现在直接从数据库读取消息
        # 这个handler只用于触发检查，不再收集消息
        
        # 始终继续处理（不影响其他插件）
        return HandlerResult(success=True, continue_process=True)
