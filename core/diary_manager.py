"""
日记管理器 - 核心逻辑模块
简单粗暴版：直接从数据库读取，按字数限制生成

数据结构：每天一个独立JSON文件，存储三个版本（today/yesterday/older）
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
        self.config = config
        
        plugin_dir = Path(__file__).parent.parent
        self.data_dir = plugin_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

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
        
        # 字数限制
        self.group_today_max_words = config.get("group_today_max_words", 2000)
        self.group_yesterday_max_words = config.get("group_yesterday_max_words", 1000)
        self.group_older_max_words = config.get("group_older_max_words", 500)
        self.private_today_max_words = config.get("private_today_max_words", 1500)
        self.private_yesterday_max_words = config.get("private_yesterday_max_words", 800)
        self.private_older_max_words = config.get("private_older_max_words", 400)
        
        # 模型上下文限制
        self.model_context_limit_k = config.get("model_context_limit_k", 100)
        self.model_context_limit = self.model_context_limit_k * 1000

        # 并发控制
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._checked_conversations: set[str] = set()

        logger.info(f"[DiaryManager] 初始化完成，数据目录: {self.data_dir}")

    def _get_lock(self, conversation_id: str) -> asyncio.Lock:
        if conversation_id not in self._locks:
            self._locks[conversation_id] = asyncio.Lock()
        return self._locks[conversation_id]

    # ==================== 路径管理 ====================
    
    def _sanitize_folder_name(self, name: str) -> str:
        """清理文件夹名称中的非法字符"""
        for char in r'<>:"/\\|?*':
            name = name.replace(char, "_")
        return name[:50]
    
    async def _get_conversation_info(self, stream_id: str) -> tuple[str, str, str]:
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
                object_name = getattr(chat_stream.user_info, 'nickname', None) or f"用户{object_id}"
            else:
                return "unknown", stream_id[:16], "未知对话"
            
            object_name = self._sanitize_folder_name(object_name)
            return chat_type, object_id, object_name
        except Exception as e:
            logger.error(f"[DiaryManager] 获取对话信息失败: {e}")
            return "unknown", stream_id[:16], "未知对话"

    def _find_folder_by_id(self, type_dir: Path, object_id: str) -> Path | None:
        """
        按 ID 前缀查找已存在的文件夹
        文件夹格式: {object_id}_{object_name}
        """
        if not type_dir.exists():
            return None
        
        prefix = f"{object_id}_"
        matching = [d for d in type_dir.iterdir() if d.is_dir() and d.name.startswith(prefix)]
        
        if len(matching) == 1:
            return matching[0]
        elif len(matching) > 1:
            # 多个匹配（不应该发生），返回最新修改的
            logger.warning(f"[DiaryManager] 发现多个匹配文件夹: {[d.name for d in matching]}，使用最新的")
            return max(matching, key=lambda d: d.stat().st_mtime)
        return None

    async def _get_conversation_folder(self, stream_id: str) -> Path:
        """
        获取对话数据文件夹，支持按 ID 锚定和自动重命名
        
        逻辑:
        1. 获取当前对话信息（chat_type, object_id, object_name）
        2. 在对应类型目录下按 ID 前缀查找已存在的文件夹
        3. 如果找到但名称不同，安全重命名为新名称
        4. 如果未找到，创建新文件夹
        """
        chat_type, object_id, object_name = await self._get_conversation_info(stream_id)
        type_dir = self.data_dir / chat_type
        type_dir.mkdir(parents=True, exist_ok=True)
        
        expected_name = f"{object_id}_{object_name}"
        expected_path = type_dir / expected_name
        
        # 查找已存在的文件夹
        existing_folder = self._find_folder_by_id(type_dir, object_id)
        
        if existing_folder:
            if existing_folder.name != expected_name:
                # 名称变化，需要重命名
                try:
                    # 确保目标不存在
                    if expected_path.exists():
                        logger.warning(f"[DiaryManager] 目标文件夹已存在，跳过重命名: {expected_path}")
                        return expected_path
                    
                    # 安全重命名
                    existing_folder.rename(expected_path)
                    logger.info(f"[DiaryManager] 文件夹重命名: {existing_folder.name} → {expected_name}")
                    return expected_path
                except Exception as e:
                    logger.error(f"[DiaryManager] 重命名失败，使用原文件夹: {e}")
                    return existing_folder
            else:
                # 名称相同，直接返回
                return existing_folder
        else:
            # 未找到，创建新文件夹
            expected_path.mkdir(parents=True, exist_ok=True)
            return expected_path
    
    async def _get_date_file(self, stream_id: str, date: str) -> Path:
        folder = await self._get_conversation_folder(stream_id)
        return folder / f"{date}.json"

    # ==================== 数据读写 ====================
    
    def _create_empty_data(self, date: str) -> dict:
        return {
            "date": date,
            "today_version": {"content": "", "message_count": 0, "word_count": 0, "updated_at": None},
            "yesterday_version": {"content": "", "word_count": 0, "created_at": None},
            "older_version": {"content": "", "word_count": 0, "created_at": None},
            "last_summary_time": None,
            "metadata": {"identity": "", "chat_type": "", "stream_id": ""}
        }
    
    async def _load_date_data(self, stream_id: str, date: str) -> dict:
        file_path = await self._get_date_file(stream_id, date)
        if not file_path.exists():
            return self._create_empty_data(date)
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            # 兼容旧版本
            if "today_version" not in data:
                new_data = self._create_empty_data(date)
                if "summary" in data:
                    new_data["today_version"]["content"] = data["summary"].get("content", "")
                    new_data["today_version"]["message_count"] = data["summary"].get("message_count", 0)
                new_data["metadata"] = data.get("metadata", new_data["metadata"])
                return new_data
            return data
        except:
            return self._create_empty_data(date)
    
    async def _save_date_data(self, stream_id: str, date: str, data: dict):
        file_path = await self._get_date_file(stream_id, date)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[DiaryManager] 保存失败: {e}")

    # ==================== 消息读取 ====================
    
    async def _fetch_messages_in_range(self, conversation_id: str, start_ts: float, end_ts: float) -> list[dict]:
        from src.chat.utils.chat_message_builder import get_raw_msg_by_timestamp_with_chat
        
        messages = []
        batch_size = 1000
        current_start = start_ts
        
        try:
            while current_start < end_ts and len(messages) < 5000:
                batch = await get_raw_msg_by_timestamp_with_chat(
                    chat_id=conversation_id,
                    timestamp_start=current_start,
                    timestamp_end=end_ts,
                    limit=batch_size,
                    limit_mode="earliest",
                )
                if not batch:
                    break
                for msg in batch:
                    messages.append({
                        "time": datetime.fromtimestamp(msg.get("time", 0)).isoformat(),
                        "sender": msg.get("user_nickname", "未知"),
                        "content": msg.get("processed_plain_text", ""),
                    })
                if len(batch) < batch_size:
                    break
                current_start = batch[-1].get("time", current_start) + 0.001
        except Exception as e:
            logger.error(f"[DiaryManager] 读取消息失败: {e}")
        
        return messages

    # ==================== 字数限制 ====================
    
    def _get_word_limit(self, version_type: str, chat_type: str) -> int:
        if chat_type == "group":
            limits = {"today": self.group_today_max_words, "yesterday": self.group_yesterday_max_words, "older": self.group_older_max_words}
        else:
            limits = {"today": self.private_today_max_words, "yesterday": self.private_yesterday_max_words, "older": self.private_older_max_words}
        return limits.get(version_type, limits["today"])

    # ==================== 核心：生成指定版本的总结 ====================
    
    async def generate_version(
        self,
        conversation_id: str,
        target_date: str,
        version_type: str,  # "today" | "yesterday" | "older"
        identity: str,
        chat_type: str,
        force: bool = False
    ) -> bool:
        """
        为指定日期生成指定版本的总结
        简单粗暴：直接从数据库读取该天全部消息，按字数限制生成
        """
        async with self._get_lock(conversation_id):
            try:
                data = await self._load_date_data(conversation_id, target_date)
                version_key = f"{version_type}_version"
                
                # 检查是否已有
                if not force and data[version_key].get("content"):
                    logger.debug(f"[DiaryManager] {target_date} 已有 {version_type} 版本")
                    return True
                
                # 计算时间范围
                date_obj = datetime.strptime(target_date, "%Y-%m-%d")
                start_ts = date_obj.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                if target_date == datetime.now().strftime("%Y-%m-%d"):
                    end_ts = datetime.now().timestamp()
                else:
                    end_ts = date_obj.replace(hour=23, minute=59, second=59).timestamp()
                
                # 从数据库读取消息
                messages = await self._fetch_messages_in_range(conversation_id, start_ts, end_ts)
                if not messages:
                    logger.info(f"[DiaryManager] {target_date} 没有消息")
                    return False
                
                # 获取字数限制
                max_words = self._get_word_limit(version_type, chat_type)
                
                logger.info(f"[DiaryManager] 生成 {target_date} {version_type} 版本，消息: {len(messages)}，字数限制: {max_words}")
                
                # 调用 LLM
                from .diary_summarizer import DiarySummarizer
                summarizer = DiarySummarizer(self.config)
                
                result = await summarizer.generate_summary(
                    messages=messages,
                    identity=identity,
                    conversation_type=chat_type,
                    target_max_words=max_words,
                    date_type=version_type,
                )
                summary_content = result.get("diary_content", "")
                
                if not summary_content:
                    logger.warning(f"[DiaryManager] 生成结果为空")
                    return False
                
                # 保存
                data[version_key] = {
                    "content": summary_content,
                    "message_count": len(messages) if version_type == "today" else 0,
                    "word_count": len(summary_content),
                    "updated_at" if version_type == "today" else "created_at": datetime.now().isoformat(),
                }
                if version_type == "today":
                    data["last_summary_time"] = datetime.now().isoformat()
                data["metadata"] = {"identity": identity, "chat_type": chat_type, "stream_id": conversation_id}
                
                await self._save_date_data(conversation_id, target_date, data)
                
                logger.info(f"[DiaryManager] ✅ {target_date} {version_type} 版本生成成功，{len(summary_content)}字")
                return True
                
            except Exception as e:
                logger.error(f"[DiaryManager] 生成失败: {e}", exc_info=True)
                return False

    # ==================== 触发检查 ====================
    
    async def check_and_trigger_summary(self, conversation_id: str, identity: str, chat_type: str) -> bool:
        should_trigger = await self._should_trigger_summary(conversation_id, chat_type)
        if should_trigger:
            today = datetime.now().strftime("%Y-%m-%d")
            return await self.generate_version(conversation_id, today, "today", identity, chat_type, force=True)
        return False
    
    async def _should_trigger_summary(self, conversation_id: str, chat_type: str) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        data = await self._load_date_data(conversation_id, today)
        last_summary_time = data.get("last_summary_time")
        
        if chat_type == "group":
            trigger_type, msg_threshold, time_interval = self.group_trigger_type, self.group_message_threshold, self.group_time_interval_hours
        else:
            trigger_type, msg_threshold, time_interval = self.private_trigger_type, self.private_message_threshold, self.private_time_interval_hours
        
        msg_ready = time_ready = False
        
        if trigger_type in ["message", "both", "any"]:
            pending = await self.get_pending_count(conversation_id)
            msg_ready = pending >= msg_threshold
        
        if trigger_type in ["time", "both", "any"]:
            if last_summary_time:
                elapsed = (datetime.now() - datetime.fromisoformat(last_summary_time)).total_seconds() / 3600
                time_ready = elapsed >= time_interval
            else:
                time_ready = True
        
        if trigger_type == "message": return msg_ready
        if trigger_type == "time": return time_ready
        if trigger_type == "both": return msg_ready and time_ready
        if trigger_type == "any": return msg_ready or time_ready
        return False

    async def get_pending_count(self, conversation_id: str) -> int:
        import time as time_module
        from src.chat.utils.chat_message_builder import get_raw_msg_by_timestamp_with_chat
        
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            data = await self._load_date_data(conversation_id, today)
            last_time = data.get("last_summary_time")
            
            if last_time:
                start_ts = datetime.fromisoformat(last_time).timestamp()
            else:
                start_ts = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            
            messages = await get_raw_msg_by_timestamp_with_chat(
                chat_id=conversation_id,
                timestamp_start=start_ts,
                timestamp_end=time_module.time(),
                limit=1000,
            )
            return len(messages)
        except:
            return 0

    # ==================== 获取日记内容 ====================
    
    async def get_diary_for_prompt(self, conversation_id: str) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        day_before = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        
        parts = []
        
        # 检查今天是否有总结
        today_data = await self._load_date_data(conversation_id, today)
        has_today = bool(today_data["today_version"]["content"])
        
        # 首次激活时检查并生成历史版本
        if has_today and conversation_id not in self._checked_conversations:
            identity = today_data["metadata"].get("identity", "")
            chat_type = today_data["metadata"].get("chat_type", "group")
            if identity:
                await self._ensure_history_versions(conversation_id, identity, chat_type)
            self._checked_conversations.add(conversation_id)
        
        # 读取今天
        if today_data["today_version"]["content"]:
            parts.append(f"【今天】\n{today_data['today_version']['content']}")
        
        # 读取昨天
        yesterday_data = await self._load_date_data(conversation_id, yesterday)
        yesterday_content = yesterday_data["yesterday_version"].get("content") or yesterday_data["today_version"].get("content")
        if yesterday_content:
            parts.append(f"【昨天】\n{yesterday_content}")
        
        # 读取前天
        older_data = await self._load_date_data(conversation_id, day_before)
        older_content = older_data["older_version"].get("content") or older_data["yesterday_version"].get("content") or older_data["today_version"].get("content")
        if older_content:
            parts.append(f"【前天】\n{older_content}")
        
        return "\n\n---\n\n".join(parts) if parts else ""
    
    async def _ensure_history_versions(self, conversation_id: str, identity: str, chat_type: str):
        """确保昨天和前天有对应的压缩版本"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        day_before = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        
        # 昨天的 yesterday_version
        yesterday_data = await self._load_date_data(conversation_id, yesterday)
        if yesterday_data["today_version"]["content"] and not yesterday_data["yesterday_version"]["content"]:
            logger.info(f"[DiaryManager] 为昨天({yesterday})生成 yesterday_version")
            await self.generate_version(conversation_id, yesterday, "yesterday", identity, chat_type)
        
        # 前天的 older_version
        older_data = await self._load_date_data(conversation_id, day_before)
        if (older_data["today_version"]["content"] or older_data["yesterday_version"]["content"]) and not older_data["older_version"]["content"]:
            logger.info(f"[DiaryManager] 为前天({day_before})生成 older_version")
            await self.generate_version(conversation_id, day_before, "older", identity, chat_type)

    # ==================== 启动检查 ====================
    
    def _read_file_directly(self, file_path: Path) -> dict | None:
        """直接读取文件，不经过动态路径查找"""
        if not file_path.exists():
            return None
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except:
            return None
    
    def _has_version_content(self, data: dict | None, version_key: str) -> bool:
        """检查数据中是否有指定版本的内容"""
        if not data:
            return False
        # 检查新格式
        if data.get(version_key, {}).get("content"):
            return True
        # 兼容旧格式
        if version_key == "today_version" and data.get("summary", {}).get("content"):
            return True
        return False
    
    async def startup_completion_check(self):
        async with self._global_lock:
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            day_before = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
            
            count = 0
            skipped = 0
            generated = 0
            logger.info("[DiaryManager] 开始启动检查...")
            
            for chat_type_name in ["group", "private"]:
                type_dir = self.data_dir / chat_type_name
                if not type_dir.exists():
                    continue
                
                for conv_dir in type_dir.iterdir():
                    if not conv_dir.is_dir():
                        continue
                    
                    today_file = conv_dir / f"{today}.json"
                    if not today_file.exists():
                        continue
                    
                    try:
                        today_data = self._read_file_directly(today_file)
                        if not today_data:
                            continue
                        
                        # 检查是否有内容
                        has_content = self._has_version_content(today_data, "today_version")
                        if not has_content:
                            continue
                        
                        metadata = today_data.get("metadata", {})
                        identity = metadata.get("identity", "")
                        chat_type = metadata.get("chat_type", chat_type_name)
                        stream_id = metadata.get("stream_id", "")
                        
                        if not identity or not stream_id:
                            continue
                        
                        count += 1
                        
                        # 检查并生成昨天的 yesterday_version
                        yesterday_file = conv_dir / f"{yesterday}.json"
                        if yesterday_file.exists():
                            yesterday_data = self._read_file_directly(yesterday_file)
                            # 只有当没有 yesterday_version 但有 today_version 时才生成
                            if (self._has_version_content(yesterday_data, "today_version") and
                                not self._has_version_content(yesterday_data, "yesterday_version")):
                                logger.info(f"[DiaryManager] 为 {yesterday} 生成 yesterday_version")
                                if await self.generate_version(stream_id, yesterday, "yesterday", identity, chat_type):
                                    generated += 1
                            else:
                                skipped += 1
                        
                        # 检查并生成前天的 older_version
                        older_file = conv_dir / f"{day_before}.json"
                        if older_file.exists():
                            older_data = self._read_file_directly(older_file)
                            # 只有当有内容但没有 older_version 时才生成
                            has_source = (self._has_version_content(older_data, "today_version") or
                                         self._has_version_content(older_data, "yesterday_version"))
                            if has_source and not self._has_version_content(older_data, "older_version"):
                                logger.info(f"[DiaryManager] 为 {day_before} 生成 older_version")
                                if await self.generate_version(stream_id, day_before, "older", identity, chat_type):
                                    generated += 1
                            else:
                                skipped += 1
                        
                        self._checked_conversations.add(stream_id)
                        
                    except Exception as e:
                        logger.error(f"[DiaryManager] 检查失败: {e}")
            
            logger.info(f"[DiaryManager] 启动检查完成，{count} 个对话，生成 {generated} 个版本，跳过 {skipped} 个已有版本")

    # ==================== 命令支持 ====================
    
    async def get_summary_status(self, conversation_id: str, date_type: str = "today") -> str:
        if date_type == "today":
            date = datetime.now().strftime("%Y-%m-%d")
            version_key = "today_version"
        elif date_type == "yesterday":
            date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            version_key = "yesterday_version"
        else:
            date = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
            version_key = "older_version"
        
        data = await self._load_date_data(conversation_id, date)
        version = data.get(version_key, {})
        
        if version.get("content"):
            word_count = version.get("word_count", len(version["content"]))
            msg_count = version.get("message_count", 0)
            return f"✅ {word_count}字" + (f" ({msg_count}条)" if msg_count else "")
        
        # 检查是否有其他版本
        for fallback in ["today_version", "yesterday_version", "older_version"]:
            if data.get(fallback, {}).get("content"):
                return f"⚠️ 有其他版本可用"
        return "❌ 无"
    
    async def refresh_all_dates(self, conversation_id: str, identity: str, chat_type: str) -> tuple[int, int]:
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        day_before = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        
        success = 0
        if await self.generate_version(conversation_id, today, "today", identity, chat_type, force=True):
            success += 1
        if await self.generate_version(conversation_id, yesterday, "yesterday", identity, chat_type, force=True):
            success += 1
        if await self.generate_version(conversation_id, day_before, "older", identity, chat_type, force=True):
            success += 1
        
        return success, 3

    async def clear_conversation(self, conversation_id: str):
        async with self._get_lock(conversation_id):
            try:
                folder = await self._get_conversation_folder(conversation_id)
                if folder.exists():
                    import shutil
                    shutil.rmtree(folder)
                    logger.info(f"[DiaryManager] 已清空 {conversation_id[:16]}...")
            except Exception as e:
                logger.error(f"[DiaryManager] 清空失败: {e}")
