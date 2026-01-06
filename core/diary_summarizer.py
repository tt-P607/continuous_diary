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

    def _calculate_time_based_word_limit(self, conversation_type: str) -> tuple[int, str]:
        """
        根据当前时间段计算字数限制（使用系统本地时区时间）
        
        Returns:
            tuple[int, str]: (字数限制, 时间段描述)
        """
        from datetime import datetime
        
        base_words = self.group_today_max_words if conversation_type == "group" else self.private_today_max_words
        # 使用本地时区的当前时间（不是UTC）
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
        self, messages: list[dict], identity: str, conversation_type: str
    ) -> dict:
        """
        生成日记式总结

        Args:
            messages: 消息列表
            identity: bot的人设描述
            conversation_type: 对话类型（"group" 或 "private"）

        Returns:
            dict: 总结对象
        """
        # 根据时间段计算字数限制
        max_words, period = self._calculate_time_based_word_limit(conversation_type)
        
        # 1. 构建消息文本
        messages_text = self._format_messages(messages)

        # 2. 构建prompt（传入时间段和字数信息）
        prompt = self._build_summary_prompt(
            messages_text=messages_text,
            identity=identity,
            conversation_type=conversation_type,
            max_words=max_words,
            period=period,
        )

        # 3. 调用LLM（使用主回复模型）
        from src.config.config import model_config
        from src.llm_models.utils_model import LLMRequest

        # 获取主回复模型配置
        if not model_config or not model_config.model_task_config:
            raise ValueError("模型配置未初始化")
        
        llm = LLMRequest(
            model_set=model_config.model_task_config.replyer,
            request_type="continuous_diary_summary",
        )

        max_tokens = int(max_words * 2.5)

        logger.debug(
            f"[DiarySummarizer] 调用LLM生成总结，消息数={len(messages)}, "
            f"时间段={period}, 目标字数={max_words}, max_tokens={max_tokens}"
        )

        result = await llm.generate_response_async(
            prompt, temperature=0.3, max_tokens=max_tokens
        )
        
        # 解包返回值（可能是tuple[str, tuple] 或其他格式）
        if isinstance(result, tuple) and len(result) >= 1:
            summary_text = result[0]
        else:
            summary_text = str(result)

        # 5. 返回总结对象
        return {
            "id": f"diary_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "start_time": messages[0]["time"],
            "end_time": messages[-1]["time"],
            "message_count": len(messages),
            "diary_content": summary_text.strip(),
            "created_at": datetime.now().isoformat(),
        }

    def _build_summary_prompt(
        self, messages_text: str, identity: str, conversation_type: str, max_words: int, period: str
    ) -> str:
        """构建总结prompt（主观视角，带人设）"""

        scene = "群聊" if conversation_type == "group" else "私聊"
        scene_desc = "群里和大家" if conversation_type == "group" else "和对方"
        
        # 根据时间段给出不同的提示
        if period == "早上":
            time_hint = f"现在是{period}，今天刚开始，记录一下早上发生的事就好，不用写结尾总结。"
        elif period == "中午":
            time_hint = f"现在是{period}，今天已经过了一半，继续记录中午的事情，还没到一天结束，不用写结尾总结。"
        else:  # 晚上
            time_hint = f"现在是{period}，一天快结束了，可以完整回顾今天发生的所有事情，可以写个简单的收尾感想。"
        
        # 准备示例文本（避免f-string嵌套问题）
        if conversation_type == "group":
            example = """群聊记忆片段示例：
上午10点多小明上线说代码跑不起来，看着挺急的。有人建议检查接口参数，小红也说可以试试XX工具。几个人一起帮忙，讨论了20多分钟，小明说搞定了。

中午12点半群里聊起午饭，小李说点了麻辣烫，听着就香。大家都开始说自己吃的，还推荐了好几家店，挺热闹的。

下午2点多小王说周末去爬山，讨论了时间和地点，最后定周六早上8点集合。"""
        else:
            example = """私聊记忆片段示例：
上午10点多小明发消息说最近工作压力大，讲了一会儿项目的事，确实挺累的。跟他分享了些应对办法，他说会试试。

中午他发了几张午饭照片，做得不错。夸了夸他的厨艺，他说是跟着B站学的。聊了会儿做饭的事，挺有意思。

下午3点多他问周末有没有空一起出去玩。讨论了几个地方，最后定周六去爬山，他看起来挺期待的。"""

        return f"""你需要用第一人称（"我"）整理今天在{scene}里发生的事情，作为自己的记忆片段保存起来，方便以后回想。这不是在写文学作品，就是像自己在脑海里过一遍今天发生了什么，用自然的、口语化的方式记下来。

## 你是谁
{identity}

## 今天{scene_desc}的对话记录
{messages_text}

---

整理记忆时的要求：

1. 用你平时说话的方式来记录，自然、简洁、口语化，不要写成文学作品或正式文章
2. 按时间顺序记下发生了什么，谁说了什么，你当时怎么想的
3. 完全符合你的人设和表达方式——你会关注什么？会怎么看这些事？用什么样的语气？
4. 这是真实的个人经历记录，你不是虚拟AI，你是真实的人
5. 避免过度文学化的描写和修辞，就像脑海里自然回忆一样

**重要：时间段和字数**
{time_hint}
目标字数大约{max_words}字，分几段记录即可。

参考这种记忆片段的风格：

{example}

现在，用符合你人设的方式整理记忆：
"""

    def _format_messages(self, messages: list[dict]) -> str:
        """格式化消息为文本（始终包含时间戳）"""
        lines = []
        for msg in messages:
            time_str = msg.get("time", "")
            sender = msg.get("sender", "未知")
            content = msg.get("content", "")

            # 格式化时间
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

    async def consolidate_daily_summary(
        self,
        daily_content: str,
        date: str,
        identity: str,
        conversation_type: str,
        max_words: int,
    ) -> dict:
        """
        整合一天的多个增量总结为完整的日终总结

        Args:
            daily_content: 今天所有增量总结的内容（已拼接）
            date: 日期字符串（YYYY-MM-DD）
            identity: bot的人设描述
            conversation_type: 对话类型
            max_words: 目标字数（昨天或前天的字数限制）

        Returns:
            dict: 日终总结对象
        """
        scene = "群聊" if conversation_type == "group" else "私聊"

        prompt = f"""把今天的多段记忆片段整合成一份完整的记忆。

## 你是谁
{identity}

## 基本信息
- 日期：{date}
- 场景：{scene}

## 今天的多段记忆
{daily_content}

---

整合要求：

1. 用第一人称（"我"），口语化、自然的方式记录
2. 合并重复部分，保留最重要的事，按时间顺序（上午→中午→下午→晚上）组织
3. 完全符合你的人设和表达方式，不要写成文学作品
4. 这是真实的个人记忆，你不是虚拟AI，你是真实的人
5. 因为是{"昨天" if max_words == 800 else "前天"}的记忆，精简到大概{max_words}字左右

开始整理：
"""

        from src.config.config import model_config
        from src.llm_models.utils_model import LLMRequest

        if not model_config or not model_config.model_task_config:
            raise ValueError("模型配置未初始化")

        llm = LLMRequest(
            model_set=model_config.model_task_config.replyer,
            request_type="continuous_diary_consolidate",
        )

        max_tokens = int(max_words * 2.5)

        logger.debug(
            f"[DiarySummarizer] 整合日终总结，日期={date}, 目标字数={max_words}"
        )

        result = await llm.generate_response_async(
            prompt, temperature=0.3, max_tokens=max_tokens
        )

        if isinstance(result, tuple) and len(result) >= 1:
            summary_text = result[0]
        else:
            summary_text = str(result)

        # 返回日终总结对象
        return {
            "id": f"daily_{date}",
            "date": date,
            "diary_content": summary_text.strip(),
            "created_at": datetime.now().isoformat(),
        }

    async def merge_segment_summaries(
        self,
        segment_summaries: list[str],
        identity: str,
        conversation_type: str,
        max_words: int,
    ) -> str:
        """
        合并多段总结为一个完整总结（用于防止单次消息过多爆上下文）

        Args:
            segment_summaries: 多段总结的列表
            identity: bot的人设描述
            conversation_type: 对话类型
            max_words: 目标字数

        Returns:
            str: 合并后的总结内容
        """
        scene = "群聊" if conversation_type == "group" else "私聊"
        
        # 拼接多段内容
        all_content = "\n\n---\n\n".join(segment_summaries)

        prompt = f"""刚才分了{len(segment_summaries)}段记录记忆，现在需要把这些片段整合成完整的记忆。

## 你的身份和性格
{identity}

## 场景
{scene}

## 多段记忆片段
{all_content}

---

把这几段合并成连贯的记忆片段。检查有没有重复内容，调整段落衔接，让整体更流畅。

重要：合并时要完全符合你的人设，用你的视角和表达方式来组织这些记忆。第三人称客观描述事实，但要融入你基于人设的理解和感受。

大概{max_words}字左右。

开始整理：
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

        logger.debug(
            f"[DiarySummarizer] 合并{len(segment_summaries)}段总结，目标字数={max_words}"
        )

        result = await llm.generate_response_async(
            prompt, temperature=0.3, max_tokens=max_tokens
        )

        if isinstance(result, tuple) and len(result) >= 1:
            merged_text = result[0]
        else:
            merged_text = str(result)

        return merged_text.strip()
