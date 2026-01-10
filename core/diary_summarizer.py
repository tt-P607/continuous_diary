"""
日记总结生成器 - LLM调用模块
负责调用LLM生成主观视角的日记式总结
支持配置模型和顺延重试
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
        
        # 模型配置（模型名称必须在 model_config.toml 中已定义）
        model_name_config = config.get("model_name", "")
        
        # 解析多个模型（逗号分隔）
        if model_name_config:
            self.model_list = [m.strip() for m in model_name_config.split(",") if m.strip()]
        else:
            self.model_list = []
        
        # 缓存的 TaskConfig（延迟初始化）
        self._custom_task_config = None
        self._task_config_initialized = False

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

        # 调用LLM（支持顺延重试）
        max_tokens = int(max_words * 2.5)
        
        summary_text = await self._call_llm_with_retry(
            prompt=prompt,
            max_tokens=max_tokens,
            request_type="continuous_diary_summary"
        )
        
        if not summary_text:
            raise ValueError("LLM 调用失败，所有模型都返回空结果")

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

        return f"""你现在正在回想刚才在{scene}里发生的事情。请以第一人称（"我"）的视角，把这段经历转化为你脑海中自然留存的记忆。

## 你的身份
{identity}

## 原始对话参考（共{message_count}条消息）
{messages_text}

---

## 记忆整理原则（请像人类大脑一样思考）

1. **模糊时间感**：严禁记录精确到分钟的时间点（如 [17:01]）。人类记忆是模糊的，请使用“刚才”、“过了一会儿”、“快结束时”或者简单的“上午”、“深夜”等自然过渡。
2. **去结构化**：不要使用列表、不要使用 [时间段] 这种生硬的标题。记忆应该是连贯的叙述，像一段流动的内心独白。
3. **严禁动作描写**：禁止出现任何括号内的动作、神态或环境描写（如“（笑）”、“（揉眼睛）”）。你是在回想，不是在演戏。
4. **侧重印象与情感**：
   - 谁让你印象深刻？他们当时是什么情绪？
   - 你们达成了什么共识或约定？
   - “我”对这些事的真实感受或随后的思考是什么？
5. **自然口语化**：用最自然的语气，就像你在对自己说话。去掉所有华丽的修辞和剧本感。

## 记忆深度
{time_hint}
- **字数上限**：{max_words}字。
- **原则**：这个数字是你的**最大容量限制**，而不是必须达到的目标。
- **核心要求**：在保证**信息完整性**（重要的人、事、情、约定）的前提下，能用多少字说清楚就用多少字。
- **拒绝水话**：如果当天没什么大事，寥寥数语即可；如果内容极其丰富，请在不超限的前提下尽可能详尽。严禁为了凑字数而啰嗦，也严禁为了省字数而丢失关键记忆。

现在，闭上眼睛回想一下，这段时间发生了什么：
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

    def _get_custom_task_config(self):
        """
        获取自定义的 TaskConfig（延迟初始化）
        
        检查配置的模型是否在 model_config 中存在，如果存在则创建 TaskConfig
        """
        if self._task_config_initialized:
            return self._custom_task_config
        
        self._task_config_initialized = True
        
        if not self.model_list:
            return None
        
        try:
            from src.config.api_ada_configs import TaskConfig
            from src.config.config import model_config
            
            if not model_config:
                logger.warning("[DiarySummarizer] model_config 未初始化，无法使用自定义模型")
                return None
            
            # 验证所有配置的模型都存在于 model_config 中
            valid_models = []
            for model_name in self.model_list:
                try:
                    model_config.get_model_info(model_name)
                    valid_models.append(model_name)
                except KeyError:
                    logger.warning(f"[DiarySummarizer] 模型 '{model_name}' 未在 model_config.toml 中定义，跳过")
            
            if not valid_models:
                logger.warning("[DiarySummarizer] 没有有效的自定义模型，将使用默认模型")
                return None
            
            # 创建 TaskConfig
            self._custom_task_config = TaskConfig(
                model_list=valid_models,
                max_tokens=5000,  # 足够长的输出
                temperature=0.3,
                concurrency_count=1,
            )
            
            logger.info(f"[DiarySummarizer] 使用自定义模型: {valid_models}")
            return self._custom_task_config
            
        except Exception as e:
            logger.error(f"[DiarySummarizer] 创建自定义 TaskConfig 失败: {e}")
            return None

    async def _call_llm_with_retry(
        self,
        prompt: str,
        max_tokens: int,
        request_type: str
    ) -> str:
        """
        调用LLM，支持配置模型和顺延重试
        
        优先使用配置的模型列表，失败后回退到默认模型
        模型名称必须在 model_config.toml 中已定义
        """
        from src.llm_models.utils_model import LLMRequest
        
        errors = []
        
        # 1. 先尝试配置的自定义模型列表
        custom_task_config = self._get_custom_task_config()
        if custom_task_config:
            try:
                logger.debug(f"[DiarySummarizer] 尝试自定义模型: {custom_task_config.model_list}")
                
                llm = LLMRequest(
                    model_set=custom_task_config,
                    request_type=request_type,
                )
                
                result = await llm.generate_response_async(
                    prompt, temperature=0.3, max_tokens=max_tokens
                )
                
                if isinstance(result, tuple) and len(result) >= 1:
                    text = result[0]
                else:
                    text = str(result)
                
                if text and text.strip():
                    logger.info(f"[DiarySummarizer] 自定义模型调用成功")
                    return text.strip()
                    
            except Exception as e:
                errors.append(f"自定义模型: {e}")
                logger.warning(f"[DiarySummarizer] 自定义模型失败: {e}")
        
        # 2. 回退到默认模型
        try:
            from src.config.config import model_config
            
            if model_config and model_config.model_task_config:
                logger.debug("[DiarySummarizer] 回退到默认回复模型")
                
                llm = LLMRequest(
                    model_set=model_config.model_task_config.replyer,
                    request_type=request_type,
                )
                
                result = await llm.generate_response_async(
                    prompt, temperature=0.3, max_tokens=max_tokens
                )
                
                if isinstance(result, tuple) and len(result) >= 1:
                    text = result[0]
                else:
                    text = str(result)
                
                if text and text.strip():
                    logger.info("[DiarySummarizer] 默认模型调用成功")
                    return text.strip()
                    
        except Exception as e:
            errors.append(f"默认模型: {e}")
            logger.error(f"[DiarySummarizer] 默认模型也失败: {e}")
        
        # 全部失败
        logger.error(f"[DiarySummarizer] 所有模型都失败: {errors}")
        return ""

    async def compress_summary(
        self,
        original_content: str,
        target_words: int,
        identity: str,
        version_type: str = "yesterday"
    ) -> str:
        """压缩总结到目标字数"""
        if version_type == "yesterday":
            version_desc = "昨天的记忆"
            hint = "保留主要事件和关键对话，去除细节"
        else:
            version_desc = "前天的记忆"
            hint = "只保留最重要的事，高度概括"

        prompt = f"""请将这段内心记忆进行精炼压缩，保留核心价值。

## 你的身份
{identity}

## 原始记忆（{len(original_content)}字）
{original_content}

---

## 压缩要求
这是{version_desc}，需要{hint}。

1. **严禁动作描写**：彻底删除所有括号内的动作、神态、环境或心理描写。
2. **模糊时间**：删除所有精确的时间标记，改用自然的叙述衔接，保持记忆的模糊感。
3. **保持第一人称**：继续以“我”的视角叙述。
4. **高度浓缩**：只留下最深刻的印象和最重要的结论，就像很久以后回想起这件事时剩下的残余记忆。
5. **自然连贯**：保持自然的内心独白风格，严禁使用列表。
6. **字数上限**：{target_words}字。在不丢失核心骨架的前提下，越精炼越好。

开始精炼记忆：
"""

        max_tokens = int(target_words * 2.5)
        logger.debug(f"[DiarySummarizer] 压缩总结，原{len(original_content)}字 → 目标{target_words}字")
        
        result = await self._call_llm_with_retry(
            prompt=prompt,
            max_tokens=max_tokens,
            request_type="continuous_diary_compress"
        )
        
        return result

    async def merge_segment_summaries(
        self,
        segment_summaries: list[str],
        identity: str,
        conversation_type: str,
        max_words: int,
    ) -> str:
        """合并多段总结为一个完整总结"""
        scene = "群聊" if conversation_type == "group" else "私聊"
        all_content = "\n\n---\n\n".join(segment_summaries)

        prompt = f"""请将以下几段零散的记忆片段整合成一段完整、连贯的内心记忆。

## 你的身份
{identity}

## 场景
{scene}

## 记忆片段
{all_content}

---

## 整合要求
1. **严禁动作描写**：确保整合后的内容没有任何括号内的动作、神态或表演性描写。
2. **模糊时间线**：理顺事件的先后顺序，但严禁出现精确时间点，使用自然过渡词。
3. **心流叙事**：将多段记忆融合成一段完整、流畅的内心独白，不要有明显的断层感。
4. **字数上限**：{max_words}字。确保逻辑通顺，不超限即可。

开始整合记忆：
"""

        max_tokens = int(max_words * 2.5)
        logger.debug(f"[DiarySummarizer] 合并{len(segment_summaries)}段总结，目标字数={max_words}")
        
        result = await self._call_llm_with_retry(
            prompt=prompt,
            max_tokens=max_tokens,
            request_type="continuous_diary_merge"
        )
        
        return result
