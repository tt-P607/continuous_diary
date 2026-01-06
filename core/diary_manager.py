"""
日记管理器 - 核心逻辑模块（v3.0）
负责日记数据的存储、检索和触发判断
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.common.logger import get_logger

logger = get_logger("continuous_diary.manager")


class DiaryManager:
    """日记管理器核心类"""

    def __init__(self, data_dir: Path, config: dict):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = config

        # 读取配置
        self.enabled_chat_types = config.get("enabled_chat_types", ["group", "private"])
        
        # 群聊触发配置
        self.group_trigger_type = config.get("group_trigger_type", "any")
        self.group_message_threshold = config.get("group_message_threshold", 50)
        self.group_time_interval_hours = config.get("group_time_interval_hours", 6)
        
        # 私聊触发配置
        self.private_trigger_type = config.get("private_trigger_type", "any")
        self.private_message_threshold = config.get("private_message_threshold", 30)
        self.private_time_interval_hours = config.get("private_time_interval_hours", 12)
        
        # 字数限制（群聊和私聊分开配置）
        self.group_today_max_words = config.get("group_today_max_words", 2000)
        self.group_yesterday_max_words = config.get("group_yesterday_max_words", 1000)
        self.group_older_max_words = config.get("group_older_max_words", 500)
        self.private_today_max_words = config.get("private_today_max_words", 1500)
        self.private_yesterday_max_words = config.get("private_yesterday_max_words", 800)
        self.private_older_max_words = config.get("private_older_max_words", 400)
        
        # 存储配置
        self.retention_days = config.get("retention_days", 3)
        
        # 模型上下文限制（单位：k tokens）
        self.model_context_limit_k = config.get("model_context_limit_k", 100)
        self.model_context_limit = self.model_context_limit_k * 1000  # 转为tokens
        
        plugin_dir = Path(__file__).parent.parent  # 插件根目录
        self.data_dir = plugin_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 文件锁（确保并发安全）
        self._locks: dict[str, asyncio.Lock] = {}

        logger.info(
            f"[DiaryManager] 初始化完成\n"
            f"  群聊触发: {self.group_trigger_type} (消息≥{self.group_message_threshold}, 时间≥{self.group_time_interval_hours}h)\n"
            f"  私聊触发: {self.private_trigger_type} (消息≥{self.private_message_threshold}, 时间≥{self.private_time_interval_hours}h)\n"
            f"  触发模式: time=仅时间 | message=仅消息 | both=都满足(AND) | any=任一(OR)\n"
            f"  群聊字数: 今{self.group_today_max_words} 昨{self.group_yesterday_max_words} 前{self.group_older_max_words}\n"
            f"  私聊字数: 今{self.private_today_max_words} 昨{self.private_yesterday_max_words} 前{self.private_older_max_words}\n"
            f"  存储路径: {self.data_dir} (保留{self.retention_days}天)\n"
            f"  模型上下文: {self.model_context_limit_k}k tokens (超过后均匀分段)\n"
            f"  数据结构: v3.0 - 每天独立文件，包含详细版+昨天版+前天版"
        )
    
    def _estimate_tokens(self, text: str) -> int:
        """估算文本的token数"""
        return int(len(text) / 1.5)
    
    def _calculate_even_segments(self, total_items: int, estimated_tokens: int) -> int:
        """计算需要分几段"""
        if estimated_tokens <= self.model_context_limit:
            return 1
        return (estimated_tokens + self.model_context_limit - 1) // self.model_context_limit

    def _get_lock(self, conversation_id: str) -> asyncio.Lock:
        """获取对话的锁对象"""
        if conversation_id not in self._locks:
            self._locks[conversation_id] = asyncio.Lock()
        return self._locks[conversation_id]
    
    async def _get_conversation_info(self, stream_id: str) -> tuple[str, str, str]:
        """从stream_id获取对话信息"""
        try:
            from src.chat.message_receive.chat_stream import get_chat_manager
            
            chat_manager = get_chat_manager()
            chat_stream = await chat_manager.get_stream(stream_id)
            
            if not chat_stream:
                return "unknown", stream_id[:16], "未知对话"
            
            if chat_stream.group_info:
                chat_type = "group"
                object_id = str(chat_stream.group_info.group_id)
                object_name = chat_stream.group_info.group_name or f"群{object_id}"
            elif chat_stream.user_info:
                chat_type = "private"
                object_id = str(chat_stream.user_info.user_id)
                user_name = getattr(chat_stream.user_info, 'nickname', None) or \
                           getattr(chat_stream.user_info, 'name', None) or \
                           f"用户{object_id}"
                object_name = user_name
            else:
                return "unknown", stream_id[:16], "未知对话"
            
            object_name = self._sanitize_filename(object_name)
            return chat_type, object_id, object_name
            
        except Exception as e:
            logger.error(f"[DiaryManager] 获取对话信息失败: {e}")
            return "unknown", stream_id[:16], "未知对话"
    
    def _sanitize_filename(self, name: str) -> str:
        """清理文件名中的非法字符"""
        illegal_chars = r'<>:"/\\|?*'
        for char in illegal_chars:
            name = name.replace(char, "_")
        if len(name) > 50:
            name = name[:50]
        return name

    async def _get_conversation_folder(self, stream_id: str) -> Path:
        """获取对话的文件夹路径"""
        chat_type, object_id, object_name = await self._get_conversation_info(stream_id)
        type_folder = self.data_dir / chat_type
        conversation_folder = type_folder / f"{object_id}_{object_name}"
        conversation_folder.mkdir(parents=True, exist_ok=True)
        return conversation_folder
    
    async def _get_conversation_file(self, stream_id: str, date: str | None = None) -> Path:
        """获取对话的数据文件路径"""
        folder = await self._get_conversation_folder(stream_id)
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        return folder / f"{date}.json"
    
    async def _get_metadata_file(self, stream_id: str) -> Path:
        """获取对话的元数据文件路径"""
        folder = await self._get_conversation_folder(stream_id)
        return folder / "metadata.json"
    
    async def _load_metadata(self, stream_id: str) -> dict:
        """加载对话的元数据"""
        metadata_file = await self._get_metadata_file(stream_id)
        if metadata_file.exists():
            try:
                with open(metadata_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[DiaryManager] 加载元数据失败: {e}")
        
        return {
            "stream_id": stream_id,
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
        }
    
    async def _save_metadata(self, stream_id: str, metadata: dict):
        """保存对话的元数据"""
        metadata_file = await self._get_metadata_file(stream_id)
        metadata["last_updated"] = datetime.now().isoformat()
        try:
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[DiaryManager] 保存元数据失败: {e}")

    async def _load_conversation(self, stream_id: str, date: str | None = None) -> dict[str, Any]:
        """加载或创建对话数据"""
        file_path = await self._get_conversation_file(stream_id, date)

        if file_path.exists():
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
                data = self._ensure_data_structure(data, stream_id)
                return data
            except Exception as e:
                logger.error(
                    f"[DiaryManager] 加载对话数据失败 {stream_id[:16]}... {date}: {e}",
                    exc_info=True
                )

        return self._create_new_data_structure(stream_id)
    
    def _create_new_data_structure(self, conversation_id: str) -> dict[str, Any]:
        """创建新的v3.0数据结构"""
        return {
            "conversation_id": conversation_id,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "detailed_summaries": [],  # 当天的多个增量总结
            "yesterday_version": None,  # 作为"昨天"的完整版本
            "older_version": None,      # 作为"前天"的精简版本
            "last_summary_time": None,
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "total_summaries": 0,
                "version": "3.0",
            },
        }
    
    def _ensure_data_structure(self, data: dict, conversation_id: str) -> dict:
        """确保数据结构完整（v3.0）"""
        version = data.get("metadata", {}).get("version", "unknown")
        
        if version != "3.0":
            logger.warning(f"[DiaryManager] 检测到非v3.0数据 (v{version})，重建: {conversation_id[:16]}...")
            return self._create_new_data_structure(conversation_id)
        
        if not isinstance(data.get("detailed_summaries"), list):
            data["detailed_summaries"] = []
        if "yesterday_version" not in data:
            data["yesterday_version"] = None
        if "older_version" not in data:
            data["older_version"] = None
        if "date" not in data:
            data["date"] = datetime.now().strftime("%Y-%m-%d")
        if "last_summary_time" not in data:
            data["last_summary_time"] = None
        if "metadata" not in data:
            data["metadata"] = {
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "total_summaries": 0,
                "version": "3.0",
            }
        else:
            data["metadata"]["version"] = "3.0"
            data["metadata"]["updated_at"] = datetime.now().isoformat()
        
        return data

    async def _save_conversation(self, stream_id: str, conv_data: dict, date: str | None = None):
        """保存对话数据"""
        file_path = await self._get_conversation_file(stream_id, date)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(conv_data, f, ensure_ascii=False, indent=2)
            metadata = await self._load_metadata(stream_id)
            await self._save_metadata(stream_id, metadata)
        except Exception as e:
            logger.error(f"[DiaryManager] 保存对话数据失败 {stream_id[:16]}... {date}: {e}")

    async def _should_trigger_summary(self, conversation_id: str, chat_type: str) -> bool:
        """判断是否触发总结（支持4种模式：time/message/both/any）"""
        conv_data = await self._load_conversation(conversation_id)
        last_summary_time = conv_data.get("last_summary_time")
        
        # 根据聊天类型选择配置
        if chat_type == "group":
            trigger_type = self.group_trigger_type
            message_threshold = self.group_message_threshold
            time_interval = self.group_time_interval_hours
        else:  # private
            trigger_type = self.private_trigger_type
            message_threshold = self.private_message_threshold
            time_interval = self.private_time_interval_hours
        
        message_ready = False
        time_ready = False
        
        # 条件1：消息数达到阈值
        if trigger_type in ["message", "both", "any"]:
            pending_count = await self.get_pending_count(conversation_id)
            message_ready = pending_count >= message_threshold
            if message_ready:
                logger.debug(f"[DiaryManager] 消息条件满足: {pending_count} >= {message_threshold}")

        # 条件2：时间间隔达到阈值
        if trigger_type in ["time", "both", "any"]:
            if last_summary_time:
                last_time = datetime.fromisoformat(last_summary_time)
                elapsed = (datetime.now() - last_time).total_seconds() / 3600
                time_ready = elapsed >= time_interval
                if time_ready:
                    logger.debug(f"[DiaryManager] 时间条件满足: {elapsed:.1f}h >= {time_interval}h")
            else:
                time_ready = True
        
        # 根据trigger_type判断
        if trigger_type == "message":
            return message_ready
        elif trigger_type == "time":
            return time_ready
        elif trigger_type == "both":
            return message_ready and time_ready
        elif trigger_type == "any":
            return message_ready or time_ready
        else:
            logger.warning(f"[DiaryManager] 未知的触发类型: {trigger_type}")
            return False

    async def trigger_summary(
        self, conversation_id: str, identity: str, conversation_type: str = "group"
    ) -> bool:
        """触发今天的增量总结生成（从数据库读取消息，支持模型失败重试）"""
        import time as time_module
        from src.chat.utils.chat_message_builder import (
            get_raw_msg_by_timestamp_with_chat,
            get_raw_msg_before_timestamp_with_chat
        )
        from src.config.config import model_config
        
        # 获取模型列表
        if not model_config or not model_config.model_task_config:
            logger.error("[DiaryManager] 模型配置未初始化")
            return False
        
        model_set = model_config.model_task_config.replyer
        model_list = getattr(model_set, 'model_list', [model_set]) if model_set else []
        
        if not model_list:
            logger.error("[DiaryManager] 没有可用的模型")
            return False
        
        logger.info(f"[DiaryManager] 可用模型数: {len(model_list)}")
        
        async with self._get_lock(conversation_id):
            conv_data = await self._load_conversation(conversation_id)
            last_summary_time = conv_data.get("last_summary_time")
            
            # 从数据库分页获取所有消息（底层有1000条限制，需要循环读取）
            raw_messages = []
            batch_size = 1000
            
            if last_summary_time:
                # 有上次总结时间，获取从那时到现在的所有消息
                last_time = datetime.fromisoformat(last_summary_time).timestamp()
                current_start = last_time
                
                while True:
                    batch = await get_raw_msg_by_timestamp_with_chat(
                        chat_id=conversation_id,
                        timestamp_start=current_start,
                        timestamp_end=time_module.time(),
                        limit=batch_size,
                        limit_mode="earliest",  # 获取最早的batch_size条
                    )
                    if not batch:
                        break
                    raw_messages.extend(batch)
                    # 如果这批数据少于batch_size，说明已经读完了
                    if len(batch) < batch_size:
                        break
                    # 更新起始时间戳为这批最后一条消息的时间
                    current_start = batch[-1]["time"]
                    logger.debug(f"[DiaryManager] 已读取 {len(raw_messages)} 条消息，继续分页...")
            else:
                # 没有上次总结时间，读取今天零点到现在的消息（首次总结）
                current_time = time_module.time()
                today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                current_start = today_start
                
                logger.info(f"[DiaryManager] 首次总结，读取今天零点到现在的消息")
                
                while True:
                    batch = await get_raw_msg_by_timestamp_with_chat(
                        chat_id=conversation_id,
                        timestamp_start=current_start,
                        timestamp_end=current_time,
                        limit=batch_size,
                        limit_mode="earliest",
                    )
                    if not batch:
                        break
                    raw_messages.extend(batch)
                    # 如果这批数据少于batch_size，说明已经读完了
                    if len(batch) < batch_size:
                        break
                    # 更新起始时间戳为这批最后一条消息的时间
                    current_start = batch[-1]["time"]
                    logger.debug(f"[DiaryManager] 已读取 {len(raw_messages)} 条消息，继续分页...")
            
            if not raw_messages:
                logger.warning(f"[DiaryManager] 对话 {conversation_id[:16]}... 无待处理消息")
                return False
            
            logger.info(f"[DiaryManager] 共读取 {len(raw_messages)} 条待总结消息")
            
            # 转换消息格式
            messages = []
            for msg in raw_messages:
                messages.append({
                    "time": datetime.fromtimestamp(msg.get("time", 0)).isoformat(),
                    "sender": msg.get("user_nickname", "未知"),
                    "content": msg.get("processed_plain_text", ""),
                })
            
            logger.info(f"[DiaryManager] 从数据库读取 {len(messages)} 条待总结消息")

            # 尝试每个模型
            for model_index, _ in enumerate(model_list, 1):
                try:
                    logger.info(f"[DiaryManager] 尝试模型 {model_index}/{len(model_list)}")
                    
                    from .diary_summarizer import DiarySummarizer
                    summarizer = DiarySummarizer(self.config)
                    
                    # 估算并分段
                    all_text = "\n".join(f"{m['sender']}: {m['content']}" for m in messages)
                    estimated_tokens = self._estimate_tokens(all_text)
                    segments_needed = self._calculate_even_segments(len(messages), estimated_tokens)
                    
                    if segments_needed > 1:
                        logger.info(f"[DiaryManager] 估算{estimated_tokens}tokens，分{segments_needed}段")
                        items_per_segment = len(messages) // segments_needed
                        remainder = len(messages) % segments_needed
                        segment_summaries = []
                        start_idx = 0
                        
                        for i in range(segments_needed):
                            segment_size = items_per_segment + (1 if i < remainder else 0)
                            end_idx = start_idx + segment_size
                            segment_msgs = messages[start_idx:end_idx]
                            
                            segment_summary = await summarizer.generate_summary(
                                messages=segment_msgs,
                                identity=identity,
                                conversation_type=conversation_type,
                            )
                            segment_summaries.append(segment_summary["diary_content"])
                            start_idx = end_idx
                        
                        merged_content = await summarizer.merge_segment_summaries(
                            segment_summaries=segment_summaries,
                            identity=identity,
                            conversation_type=conversation_type,
                            max_words=self.today_max_words,
                        )
                        
                        summary = {
                            "id": f"diary_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                            "start_time": messages[0]["time"],
                            "end_time": messages[-1]["time"],
                            "message_count": len(messages),
                            "diary_content": merged_content,
                            "created_at": datetime.now().isoformat(),
                        }
                    else:
                        summary = await summarizer.generate_summary(
                            messages=messages,
                            identity=identity,
                            conversation_type=conversation_type,
                        )

                    # 成功，保存
                    conv_data["detailed_summaries"].append(summary)
                    conv_data["last_summary_time"] = datetime.now().isoformat()
                    conv_data["metadata"]["total_summaries"] += 1
                    conv_data["metadata"]["identity"] = identity
                    conv_data["metadata"]["updated_at"] = datetime.now().isoformat()

                    await self._save_conversation(conversation_id, conv_data)

                    logger.info(
                        f"[DiaryManager] ✅ 对话 {conversation_id[:16]}... 生成增量总结成功，"
                        f"消息数: {summary['message_count']}, "
                        f"字数: {len(summary['diary_content'])}, "
                        f"今天已有: {len(conv_data['detailed_summaries'])}"
                    )
                    return True

                except Exception as e:
                    logger.error(
                        f"[DiaryManager] ❌ 模型 {model_index}/{len(model_list)} 失败: {e}",
                        exc_info=True
                    )
                    if model_index < len(model_list):
                        logger.info(f"[DiaryManager] 尝试下一个模型...")
                        continue
            
            logger.error(f"[DiaryManager] ❌ 所有 {len(model_list)} 个模型都失败")
            return False

    async def get_diary_for_prompt(self, conversation_id: str) -> str:
        """获取用于注入到提示词的日记内容（v3.0）"""
        async with self._get_lock(conversation_id):
            try:
                # 先检查并补全缺失的版本（懒加载机制）
                await self._ensure_consolidated_versions(conversation_id)
                
                today_data = await self._load_conversation(conversation_id)
                diary_parts = []
                
                # 1. 今天的详细总结
                detailed_summaries = today_data.get("detailed_summaries", [])
                if detailed_summaries:
                    today_contents = [
                        s.get("diary_content", "")
                        for s in detailed_summaries
                        if isinstance(s, dict) and s.get("diary_content")
                    ]
                    if today_contents:
                        today_text = "\n\n".join(today_contents)
                        # 保留完整内容，不再截断
                        diary_parts.append(f"【今天】\n{today_text}")
                
                # 2. 昨天的版本
                yesterday_version = today_data.get("yesterday_version")
                if yesterday_version:
                    yesterday_text = str(yesterday_version)
                    # 保留完整内容
                    diary_parts.append(f"【昨天】\n{yesterday_text}")
                
                # 3. 前天的版本
                older_version = today_data.get("older_version")
                if older_version:
                    older_text = str(older_version)
                    # 保留完整内容
                    diary_parts.append(f"【前天】\n{older_text}")
                
                if not diary_parts:
                    return ""
                
                return "\n\n---\n\n".join(diary_parts)
                
            except Exception as e:
                logger.error(f"[DiaryManager] 获取日记内容失败: {e}", exc_info=True)
                return ""

    async def get_pending_count(self, conversation_id: str) -> int:
        """获取待处理消息数（从数据库查询）"""
        import time as time_module
        from src.chat.utils.chat_message_builder import (
            get_raw_msg_before_timestamp_with_chat,
            get_raw_msg_by_timestamp_with_chat
        )
        
        async with self._get_lock(conversation_id):
            try:
                conv_data = await self._load_conversation(conversation_id)
                last_summary_time = conv_data.get("last_summary_time")
                
                if not last_summary_time:
                    messages = await get_raw_msg_before_timestamp_with_chat(
                        chat_id=conversation_id,
                        timestamp=time_module.time(),
                        limit=1000,
                    )
                    return len(messages)
                else:
                    last_time = datetime.fromisoformat(last_summary_time).timestamp()
                    messages = await get_raw_msg_by_timestamp_with_chat(
                        chat_id=conversation_id,
                        timestamp_start=last_time,
                        timestamp_end=time_module.time(),
                    )
                    return len(messages)
            except Exception as e:
                logger.error(f"[DiaryManager] 获取待处理消息数失败: {e}")
                return 0

    async def clear_conversation(self, conversation_id: str):
        """清空对话的所有数据"""
        async with self._get_lock(conversation_id):
            try:
                folder = await self._get_conversation_folder(conversation_id)
                if folder.exists():
                    import shutil
                    shutil.rmtree(folder)
                    logger.info(f"[DiaryManager] 已清空对话 {conversation_id[:16]}... 的日记数据")
            except Exception as e:
                logger.error(f"[DiaryManager] 清空对话数据失败: {e}")

    async def consolidate_yesterday(self, conversation_id: str, yesterday_date: str) -> bool:
        """
        零点自动任务：合并昨天的多个增量总结为一个完整版本
        
        Args:
            conversation_id: 对话ID
            yesterday_date: 昨天的日期字符串（YYYY-MM-DD）
        
        Returns:
            bool: 是否成功合并（如果没有昨天的日记也返回False）
        """
        async with self._get_lock(conversation_id):
            try:
                # 读取昨天的数据文件
                yesterday_data = await self._load_conversation(conversation_id, yesterday_date)
                
                # 检查是否有详细总结
                detailed_summaries = yesterday_data.get("detailed_summaries", [])
                if not detailed_summaries:
                    return False  # 昨天没有日记，跳过
                
                # 检查是否已经合并过
                if yesterday_data.get("yesterday_version"):
                    logger.debug(f"[DiaryManager] 对话 {conversation_id[:16]}... 的 {yesterday_date} 已经合并过")
                    return False
                
                # 获取对话类型和人设
                metadata = await self._load_metadata(conversation_id)
                identity = metadata.get("metadata", {}).get("identity", "")
                chat_type, _, _ = await self._get_conversation_info(conversation_id)
                
                if not identity:
                    logger.warning(f"[DiaryManager] 对话 {conversation_id[:16]}... 没有人设信息，跳过合并")
                    return False
                
                # 拼接今天的所有增量总结
                daily_content = "\n\n---\n\n".join([
                    s.get("diary_content", "")
                    for s in detailed_summaries
                    if isinstance(s, dict) and s.get("diary_content")
                ])
                
                if not daily_content:
                    return False
                
                # 根据聊天类型选择字数限制
                max_words = self.group_yesterday_max_words if chat_type == "group" else self.private_yesterday_max_words
                
                # 调用consolidator生成完整版
                from .diary_summarizer import DiarySummarizer
                summarizer = DiarySummarizer(self.config)
                
                consolidated = await summarizer.consolidate_daily_summary(
                    daily_content=daily_content,
                    date=yesterday_date,
                    identity=identity,
                    conversation_type=chat_type,
                    max_words=max_words,
                )
                
                # 保存合并后的版本
                yesterday_data["yesterday_version"] = consolidated.get("diary_content", "")
                yesterday_data["metadata"]["consolidated_at"] = datetime.now().isoformat()
                await self._save_conversation(conversation_id, yesterday_data, yesterday_date)
                
                # 更新今天的数据，把昨天的版本链接过来
                today_data = await self._load_conversation(conversation_id)
                today_data["yesterday_version"] = consolidated.get("diary_content", "")
                
                # 同时把前天的版本也从昨天文件中读取
                if yesterday_data.get("yesterday_version"):
                    today_data["older_version"] = yesterday_data.get("yesterday_version")
                
                await self._save_conversation(conversation_id, today_data)
                
                logger.info(
                    f"[DiaryManager] ✅ 对话 {conversation_id[:16]}... 的 {yesterday_date} "
                    f"日记已合并（{len(detailed_summaries)}段 → {len(consolidated.get('diary_content', ''))}字）"
                )
                return True
                
            except Exception as e:
                logger.error(f"[DiaryManager] 合并昨天日记失败 {conversation_id[:16]}... {yesterday_date}: {e}", exc_info=True)
                return False

    async def _ensure_consolidated_versions(self, conversation_id: str):
        """懒加载机制：确保昨天和前天的版本存在，如果不存在则自动生成"""
        from datetime import datetime, timedelta
        import time as time_module
        from src.chat.utils.chat_message_builder import get_raw_msg_by_timestamp_with_chat
        
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            day_before_yesterday = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
            
            today_data = await self._load_conversation(conversation_id)
            
            # 检查1：昨天的版本是否存在
            if not today_data.get("yesterday_version"):
                logger.info(f"[DiaryManager] 检测到昨天版本缺失，尝试补全 {conversation_id[:16]}...")
                
                # 尝试从昨天的文件读取
                yesterday_file = await self._get_conversation_file(conversation_id, yesterday)
                if yesterday_file.exists():
                    yesterday_data = await self._load_conversation(conversation_id, yesterday)
                    detailed_summaries = yesterday_data.get("detailed_summaries", [])
                    
                    if detailed_summaries:
                        # 有增量总结，合并它们
                        logger.info(f"[DiaryManager] 发现昨天有{len(detailed_summaries)}段增量总结，开始合并")
                        success = await self.consolidate_yesterday(conversation_id, yesterday)
                        if success:
                            return  # 合并成功后会自动更新today_data
                    else:
                        # 昨天文件存在但没有总结，从数据库生成
                        logger.info(f"[DiaryManager] 昨天文件存在但无总结，从数据库读取原始消息生成")
                        await self._generate_from_raw_messages(conversation_id, yesterday)
                else:
                    # 昨天的文件不存在，从数据库读取原始消息
                    logger.info(f"[DiaryManager] 昨天文件不存在，从数据库读取原始消息生成")
                    await self._generate_from_raw_messages(conversation_id, yesterday)
            
            # 检查2：前天的版本是否存在
            if not today_data.get("older_version"):
                logger.info(f"[DiaryManager] 检测到前天版本缺失，尝试补全 {conversation_id[:16]}...")
                
                # 尝试从前天的文件读取
                older_file = await self._get_conversation_file(conversation_id, day_before_yesterday)
                if older_file.exists():
                    older_data = await self._load_conversation(conversation_id, day_before_yesterday)
                    
                    # 如果前天文件有yesterday_version，直接用
                    if older_data.get("yesterday_version"):
                        today_data["older_version"] = older_data["yesterday_version"]
                        await self._save_conversation(conversation_id, today_data)
                        logger.info(f"[DiaryManager] 前天版本已从文件补全")
                    elif older_data.get("detailed_summaries"):
                        # 有增量总结，合并它们
                        logger.info(f"[DiaryManager] 发现前天有增量总结，开始合并")
                        await self._consolidate_older_day(conversation_id, day_before_yesterday)
                    else:
                        # 从数据库生成
                        logger.info(f"[DiaryManager] 从数据库读取前天原始消息生成")
                        await self._generate_from_raw_messages(conversation_id, day_before_yesterday)
                else:
                    # 从数据库生成
                    logger.info(f"[DiaryManager] 前天文件不存在，从数据库生成")
                    await self._generate_from_raw_messages(conversation_id, day_before_yesterday)
                    
        except Exception as e:
            logger.error(f"[DiaryManager] 补全版本失败 {conversation_id[:16]}...: {e}", exc_info=True)

    async def _generate_from_raw_messages(self, conversation_id: str, target_date: str):
        """从数据库原始消息生成指定日期的完整总结"""
        import time as time_module
        from datetime import datetime, timedelta
        from src.chat.utils.chat_message_builder import get_raw_msg_by_timestamp_with_chat
        
        try:
            # 计算时间范围
            date_obj = datetime.strptime(target_date, "%Y-%m-%d")
            start_timestamp = date_obj.timestamp()
            end_timestamp = (date_obj + timedelta(days=1)).timestamp()
            
            # 从数据库读取原始消息
            raw_messages = []
            batch_size = 1000
            current_start = start_timestamp
            
            while current_start < end_timestamp:
                batch = await get_raw_msg_by_timestamp_with_chat(
                    chat_id=conversation_id,
                    timestamp_start=current_start,
                    timestamp_end=end_timestamp,
                    limit=batch_size,
                    limit_mode="earliest",
                )
                if not batch:
                    break
                raw_messages.extend(batch)
                if len(batch) < batch_size:
                    break
                # 更新起始时间为最后一条消息的时间
                last_msg_time = batch[-1].get("timestamp", current_start)
                current_start = last_msg_time + 0.001
            
            if not raw_messages:
                logger.info(f"[DiaryManager] {target_date} 没有原始消息，跳过")
                return
            
            # 格式化消息
            from .diary_summarizer import DiarySummarizer
            messages = []
            for msg in raw_messages:
                messages.append({
                    "sender": msg.get("sender_name", "未知"),
                    "content": msg.get("content", ""),
                    "time": datetime.fromtimestamp(msg.get("timestamp", 0)).isoformat(),
                })
            
            # 获取人设和对话类型
            metadata = await self._load_metadata(conversation_id)
            identity = metadata.get("metadata", {}).get("identity", "")
            chat_type, _, _ = await self._get_conversation_info(conversation_id)
            
            if not identity:
                logger.warning(f"[DiaryManager] 没有人设信息，跳过生成")
                return
            
            # 根据是昨天还是前天选择字数
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            
            if target_date == yesterday:
                max_words = self.group_yesterday_max_words if chat_type == "group" else self.private_yesterday_max_words
                version_key = "yesterday_version"
            else:
                max_words = self.group_older_max_words if chat_type == "group" else self.private_older_max_words
                version_key = "older_version"
            
            # 生成总结
            summarizer = DiarySummarizer(self.config)
            summary = await summarizer.generate_summary(
                messages=messages,
                identity=identity,
                conversation_type=chat_type,
            )
            
            # 如果消息太多，需要合并总结到目标字数
            summary_content = summary.get("diary_content", "")
            if len(summary_content) > max_words * 2:
                # 内容太长，再压缩一次
                consolidated = await summarizer.consolidate_daily_summary(
                    daily_content=summary_content,
                    date=target_date,
                    identity=identity,
                    conversation_type=chat_type,
                    max_words=max_words,
                )
                summary_content = consolidated.get("diary_content", "")
            
            # 保存到今天的数据中
            today_data = await self._load_conversation(conversation_id)
            today_data[version_key] = summary_content
            await self._save_conversation(conversation_id, today_data)
            
            logger.info(
                f"[DiaryManager] ✅ 从原始消息生成 {target_date} 的总结成功 "
                f"({len(messages)}条消息 → {len(summary_content)}字）"
            )
            
        except Exception as e:
            logger.error(f"[DiaryManager] 从原始消息生成总结失败 {target_date}: {e}", exc_info=True)

    async def _consolidate_older_day(self, conversation_id: str, target_date: str):
        """合并前天的增量总结"""
        try:
            older_data = await self._load_conversation(conversation_id, target_date)
            detailed_summaries = older_data.get("detailed_summaries", [])
            
            if not detailed_summaries:
                return
            
            # 拼接所有增量总结
            daily_content = "\n\n---\n\n".join([
                s.get("diary_content", "")
                for s in detailed_summaries
                if isinstance(s, dict) and s.get("diary_content")
            ])
            
            # 获取元数据
            metadata = await self._load_metadata(conversation_id)
            identity = metadata.get("metadata", {}).get("identity", "")
            chat_type, _, _ = await self._get_conversation_info(conversation_id)
            
            if not identity:
                return
            
            # 使用前天的字数限制
            max_words = self.group_older_max_words if chat_type == "group" else self.private_older_max_words
            
            # 生成合并版本
            from .diary_summarizer import DiarySummarizer
            summarizer = DiarySummarizer(self.config)
            consolidated = await summarizer.consolidate_daily_summary(
                daily_content=daily_content,
                date=target_date,
                identity=identity,
                conversation_type=chat_type,
                max_words=max_words,
            )
            
            # 更新今天的older_version
            today_data = await self._load_conversation(conversation_id)
            today_data["older_version"] = consolidated.get("diary_content", "")
            await self._save_conversation(conversation_id, today_data)
            
            logger.info(f"[DiaryManager] ✅ 前天({target_date})日记已合并")
            
        except Exception as e:
            logger.error(f"[DiaryManager] 合并前天日记失败: {e}", exc_info=True)
