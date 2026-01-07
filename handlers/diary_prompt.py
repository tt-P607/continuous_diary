"""
日记提示词注入组件
将日记内容注入到回复提示词中
"""

from typing import TYPE_CHECKING, ClassVar

from src.plugin_system import BasePrompt
from src.plugin_system.base.component_types import InjectionRule, InjectionType
from src.common.logger import get_logger

if TYPE_CHECKING:
    from ..core.diary_manager import DiaryManager

logger = get_logger("continuous_diary.prompt")


class DiaryPromptComponent(BasePrompt):
    """日记提示词组件"""

    prompt_name = "continuous_diary_prompt"
    prompt_description = "将日记式记忆注入到回复提示词中，提供完整的上下文"

    # 注入规则：注入到历史记录之前
    injection_rules = [
        # AFC 群聊场景 - s4u 模式
        InjectionRule(
            target_prompt="s4u_style_prompt",
            injection_type=InjectionType.PREPEND,
            priority=150,
        ),
        # AFC 群聊场景 - normal 模式
        InjectionRule(
            target_prompt="normal_style_prompt",
            injection_type=InjectionType.PREPEND,
            priority=150,
        ),
        # KFC 私聊场景 - 主提示词
        InjectionRule(
            target_prompt="kfc_main",
            injection_type=InjectionType.PREPEND,
            priority=150,
        ),
        # KFC 私聊场景 - 回复提示词
        InjectionRule(
            target_prompt="kfc_replyer",
            injection_type=InjectionType.PREPEND,
            priority=150,
        ),
        # KFC 私聊场景 - 统一提示词
        InjectionRule(
            target_prompt="kfc_unified_prompt",
            injection_type=InjectionType.PREPEND,
            priority=150,
        ),
    ]

    manager: ClassVar["DiaryManager | None"] = None

    def __init__(self, params, plugin_config: dict, target_prompt_name: str | None = None):
        super().__init__(params, plugin_config, target_prompt_name)

    async def execute(self) -> str:
        """执行提示词生成"""
        # 获取stream_id和类型
        stream_id, chat_type = await self._extract_stream_info()
        if not stream_id:
            return ""
        
        # 检查是否在适用范围内
        enabled_types = self.get_config("enabled_chat_types", ["group", "private"])
        if chat_type not in enabled_types:
            return ""

        # 获取日记内容
        if not self.manager:
            logger.warning("[DiaryPrompt] DiaryManager 未初始化")
            return ""

        try:
            diary_content = await self.manager.get_diary_for_prompt(stream_id)
        except Exception as e:
            logger.error(f"[DiaryPrompt] 获取日记内容失败: {e}")
            return ""

        if not diary_content:
            return ""

        # 格式化输出
        result = f"""
【你的日记回顾】
（以下是你用自己的视角记录的最近对话经历）

{diary_content}

---
（以下是最近的原始对话）
"""
        logger.debug(f"[DiaryPrompt] 注入日记内容 {len(diary_content)} 字")
        return result

    async def _extract_stream_info(self) -> tuple[str | None, str]:
        """从params中提取stream_id和聊天类型"""
        params = self.params
        
        if not params:
            return None, "unknown"

        chat_id = getattr(params, "chat_id", None) or ""
        is_group_chat = getattr(params, "is_group_chat", False)
        
        chat_type = "group" if is_group_chat else "private"
        
        if chat_id and chat_id.strip():
            return chat_id, chat_type
        
        return None, chat_type
