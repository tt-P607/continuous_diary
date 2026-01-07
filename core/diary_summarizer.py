"""
日记总结生成器 - LLM调用模块
负责调用LLM生成主观视角的日记式总结
"""

from datetime import datetime

from src.common.logger import get_logger

logger = get_logger("continuous_diary.summarizer")


class DiarySummarizer:
    """日记总结生成器"""

    def __init__(self, config: dict):
        self.config = config
        self.group_today_max_words = config.get("group_today_max_words", 2000)
        self.private_today_max_words = config.get("private_today_max_words", 1500)

    def _calculate_time_based_word_limit(self, base_words: int) -> tuple[int, str]:
        """
        根据当前时间段动态调整字数限制
        
        Returns:
            tuple[int, str]: (字数限制, 时间段描述)
        """
        current_hour = datetime.now().hour
        
        if current_hour < 8:
            ratio = 0.33
            period = "早上"
        elif current_hour < 16:
            ratio = 0.67
            period = "中午"
        else:
            ratio = 1.0
            period = "晚上"
        
        word_limit = int(base_words * ratio)
        return word_limit, period

    async def generate_summary(
        self,
        messages: list[dict],
        identity: str,
        conversation_type: str,
        target_max_words: int | None = None,
        date_type: str = "today"
    ) -> dict:
        """
        生成日记式总结

        Args:
            messages: 消息列表
            identity: bot的人设描述
            conversation_type: 对话类型（"group" 或 "private"）
            target_max_words: 目标字数上限（如果不提供则根据时间动态计算）
            date_type: 日期类型 "today" | "yesterday" | "older"

        Returns:
            dict: 总结对象
        """
        # 确定字数限制
        if target_max_words:
            # 只有今天才应用时间段动态调整
            if date_type == "today":
                max_words, period = self._calculate_time_based_word_limit(target_max_words)
            else:
                max_words = target_max_words
                period = "历史"
        else:
            base_words = self.group_today_max_words if conversation_type == "group" else self.private_today_max_words
            max_words, period = self._calculate_time_based_word_limit(base_words)
        
        # 构建消息文本
        messages_text = self._format_messages(messages)

        # 构建prompt
        prompt = self._build_summary_prompt(
            messages_text=messages_text,
            identity=identity,
            conversation_type=conversation_type,
            max_words=max_words,
            period=period,
            message_count=len(messages),
        )

        # 调用LLM
        from src.config.config import model_config
        from src.llm_models.utils_model import LLMRequest

        if not model_config or not model_config.model_task_config:
            raise ValueError("模型配置未初始化")
        
        llm = LLMRequest(
            model_set=model_config.model_task_config.replyer,
            request_type="continuous_diary_summary",
        )

        max_tokens = int(max_words * 2.5)

        logger.debug(
            f"[DiarySummarizer] 调用LLM生成总结，消息数={len(messages)}, "
            f"时间段={period}, 目标字数={max_words}"
        )

        result = await llm.generate_response_async(
            prompt, temperature=0.3, max_tokens=max_tokens
        )
        
        # 解包返回值
        if isinstance(result, tuple) and len(result) >= 1:
            summary_text = result[0]
        else:
            summary_text = str(result)

        return {
            "id": f"diary_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "start_time": messages[0]["time"] if messages else "",
            "end_time": messages[-1]["time"] if messages else "",
            "message_count": len(messages),
            "diary_content": summary_text.strip(),
            "created_at": datetime.now().isoformat(),
        }

    def _build_summary_prompt(
        self,
        messages_text: str,
        identity: str,
        conversation_type: str,
        max_words: int,
        period: str,
        message_count: int
    ) -> str:
        """构建总结prompt"""
        scene = "群聊" if conversation_type == "group" else "私聊"
        scene_desc = "群里和大家" if conversation_type == "group" else "和对方"
        
        # 时间段提示
        if period == "早上":
            time_hint = f"现在是{period}，今天刚开始。"
        elif period == "中午":
            time_hint = f"现在是{period}，今天过了一半。"
        elif period == "历史":
            time_hint = "这是历史记忆的整理。"
        else:
            time_hint = f"现在是{period}，一天快结束了。"

        return f"""用第一人称（"我"）整理在{scene}里发生的事情，作为自己的记忆片段。这些记忆之后会帮助你回忆起这段时间发生了什么。

## 你是谁
{identity}

## {scene_desc}的对话记录（共{message_count}条消息）
{messages_text}

---

## 整理原则（重要！）

**核心目标：信息完整性 > 字数控制**

1. **必须记录的内容**（不能遗漏）：
   - 讨论的主要话题和结论
   - 重要的事件、决定、约定
   - 有意义的对话内容和观点
   - 涉及到的人名和他们说了什么重要的话
   - 时间节点（大概几点发生的事）

2. **可以省略的内容**：
   - 重复的寒暄和水话
   - 表情包、无意义的回复
   - 完全相同话题的重复讨论

3. **格式要求**：
   - 自然、口语化，像脑海里回想
   - 按时间顺序组织
   - 符合你的人设和表达方式

## 字数说明
{time_hint}
- 字数上限：{max_words}字
- **原则：宁可多写确保完整，也不要为了省字数丢失信息**
- 如果对话内容确实很少，那就简短写；如果内容丰富，就详细写
- 不要刻意凑字数，但也不要刻意省略重要信息

现在开始整理记忆：
"""

    def _format_messages(self, messages: list[dict]) -> str:
        """格式化消息为文本"""
        lines = []
        for msg in messages:
            time_str = msg.get("time", "")
            sender = msg.get("sender", "未知")
            content = msg.get("content", "")

            if time_str:
                try:
                    dt = datetime.fromisoformat(time_str)
                    time_display = dt.strftime("%H:%M")
                    lines.append(f"[{time_display}] {sender}: {content}")
                except:
                    lines.append(f"{sender}: {content}")
            else:
                lines.append(f"{sender}: {content}")

        return "\n".join(lines)

    async def compress_summary(
        self,
        original_content: str,
        target_words: int,
        identity: str,
        version_type: str = "yesterday"
    ) -> str:
        """
        压缩总结到目标字数

        Args:
            original_content: 原始总结内容
            target_words: 目标字数
            identity: bot的人设描述
            version_type: "yesterday" 或 "older"

        Returns:
            str: 压缩后的内容
        """
        if version_type == "yesterday":
            version_desc = "昨天的记忆"
            hint = "保留主要事件和关键对话，去除细节"
        else:
            version_desc = "前天的记忆"
            hint = "只保留最重要的事，高度概括"

        prompt = f"""请将这段日记记忆压缩到{target_words}字左右。

## 你的身份
{identity}

## 原始记忆（{len(original_content)}字）
{original_content}

---

## 压缩要求
这是{version_desc}，需要{hint}。

1. 保持第一人称（"我"）
2. 保留重要的人名、事件、结论
3. 去除细节描写和冗余表达
4. 保持你的表达风格
5. 目标字数：{target_words}字左右

开始压缩：
"""

        from src.config.config import model_config
        from src.llm_models.utils_model import LLMRequest

        if not model_config or not model_config.model_task_config:
            raise ValueError("模型配置未初始化")

        llm = LLMRequest(
            model_set=model_config.model_task_config.replyer,
            request_type="continuous_diary_compress",
        )

        max_tokens = int(target_words * 2.5)

        logger.debug(f"[DiarySummarizer] 压缩总结，原{len(original_content)}字 → 目标{target_words}字")

        result = await llm.generate_response_async(
            prompt, temperature=0.3, max_tokens=max_tokens
        )

        if isinstance(result, tuple) and len(result) >= 1:
            compressed_text = result[0]
        else:
            compressed_text = str(result)

        return compressed_text.strip()

    async def merge_segment_summaries(
        self,
        segment_summaries: list[str],
        identity: str,
        conversation_type: str,
        max_words: int,
    ) -> str:
        """
        合并多段总结为一个完整总结

        Args:
            segment_summaries: 多段总结的列表
            identity: bot的人设描述
            conversation_type: 对话类型
            max_words: 目标字数

        Returns:
            str: 合并后的总结内容
        """
        scene = "群聊" if conversation_type == "group" else "私聊"
        
        all_content = "\n\n---\n\n".join(segment_summaries)

        prompt = f"""把这{len(segment_summaries)}段记忆片段整合成完整的记忆。

## 你的身份
{identity}

## 场景
{scene}

## 多段记忆片段
{all_content}

---

合并要求：
1. 检查有没有重复内容，调整段落衔接
2. 保持你的人设和表达方式
3. 大概{max_words}字左右

开始整合：
"""

        from src.config.config import model_config
        from src.llm_models.utils_model import LLMRequest

        if not model_config or not model_config.model_task_config:
            raise ValueError("模型配置未初始化")

        llm = LLMRequest(
            model_set=model_config.model_task_config.replyer,
            request_type="continuous_diary_merge",
        )

        max_tokens = int(max_words * 2.5)

        logger.debug(f"[DiarySummarizer] 合并{len(segment_summaries)}段总结，目标字数={max_words}")

        result = await llm.generate_response_async(
            prompt, temperature=0.3, max_tokens=max_tokens
        )

        if isinstance(result, tuple) and len(result) >= 1:
            merged_text = result[0]
        else:
            merged_text = str(result)

        return merged_text.strip()
