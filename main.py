import asyncio
import json
import time
import random
import sqlite3
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import os
from dataclasses import dataclass

from astrbot.api.provider import ProviderRequest
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
from .database_migration import SmartDatabaseMigration
from .enhanced_memory_display import EnhancedMemoryDisplay
from .embedding_cache_manager import EmbeddingCacheManager
from .enhanced_memory_recall import EnhancedMemoryRecall
from .memory_graph_visualization import MemoryGraphVisualizer
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig
from astrbot.api.star import StarTools
from .resource_management import resource_manager

@register("astrbot_plugin_memora_connect", "qa296", "赋予AI记忆与印象/好感的能力！  模仿生物海马体，通过概念节点与关系连接构建记忆网络，具备记忆形成、提取、遗忘、巩固功能，采用双峰时间分布回顾聊天，打造有记忆能力的智能对话体验。", "0.2.6", "https://github.com/qa296/astrbot_plugin_memora_connect")
class MemoraConnectPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        data_dir = StarTools.get_data_dir() / "memora_connect"
        self.memory_system = MemorySystem(context, config, data_dir)
        self.memory_display = EnhancedMemoryDisplay(self.memory_system)
        self.graph_visualizer = MemoryGraphVisualizer(self.memory_system)
        self._initialized = False
        asyncio.create_task(self._async_init())
    
    def _debug_log(self, message: str, level: str = "debug"):
        try:
            if level == "debug":
                logger.debug(message)
            elif level == "info":
                logger.info(message)
            elif level == "warning":
                logger.warning(message)
            elif level == "error":
                logger.error(message)
            else:
                logger.info(message)
        except Exception:
            pass
    
    async def _async_init(self):
        """异步初始化包装器"""
        try:
            logger.info("开始异步初始化记忆系统...")
            await self.memory_system.initialize()
            self._initialized = True
            logger.info("记忆系统异步初始化完成")
        except Exception as e:
            logger.error(f"记忆系统初始化失败: {e}", exc_info=True)
        
    @filter.command_group("记忆")
    def memory(self):
        """记忆管理指令组"""
        pass

    @memory.command("回忆")
    async def memory_recall(self, event: AstrMessageEvent, keyword: str):
        # 检查记忆系统是否启用
        if not self.memory_system.config_manager.is_memory_system_enabled():
            yield event.plain_result("记忆系统已禁用，无法使用回忆功能。")
            return
        memories = await self.memory_system.recall_memories_full(keyword)
        response = self.memory_display.format_memory_search_result(memories, keyword)
        yield event.plain_result(response)

    @memory.command("状态")
    async def memory_status(self, event: AstrMessageEvent):
        # 检查记忆系统是否启用
        if not self.memory_system.config_manager.is_memory_system_enabled():
            yield event.plain_result("记忆系统已禁用，无法查看状态。")
            return
            
        stats = self.memory_display.format_memory_statistics()
        yield event.plain_result(stats)
    @memory.command("印象")
    async def memory_impression(self, event: AstrMessageEvent, name: str):
        """查询人物印象摘要和相关记忆"""
        # 检查记忆系统是否启用
        if not self.memory_system.config_manager.is_memory_system_enabled():
            yield event.plain_result("记忆系统已禁用，无法查询印象。")
            return
            
        try:
            # 获取群组ID
            group_id = self.memory_system._extract_group_id_from_event(event)
            
            # 获取印象摘要
            impression_summary = self.memory_system.get_person_impression_summary(group_id, name)
            
            # 获取印象记忆列表
            impression_memories = self.memory_system.get_person_impression_memories(group_id, name, limit=5)
            
            # 格式化响应
            response_parts = []
            
            # 添加印象摘要
            if impression_summary:
                score = impression_summary.get("score", 0.5)
                score_desc = self.memory_system._score_to_description(score)
                response_parts.append(f"📝 {name} 的印象摘要:")
                response_parts.append(f"   印象: {impression_summary.get('summary', '无')}")
                response_parts.append(f"   好感度: {score_desc} ({score:.2f})")
                response_parts.append(f"   记忆数: {impression_summary.get('memory_count', 0)}")
                response_parts.append(f"   更新时间: {impression_summary.get('last_updated', '无')}")
            else:
                response_parts.append(f"📝 尚未建立对 {name} 的印象")
            
            # 添加相关记忆
            if impression_memories:
                response_parts.append("\n📚 相关记忆:")
                for i, memory in enumerate(impression_memories, 1):
                    response_parts.append(f"   {i}. {memory['content']}")
                    if memory.get('details'):
                        response_parts.append(f"      详情: {memory['details']}")
                    response_parts.append(f"      好感度: {memory['score']:.2f} | 时间: {memory['last_accessed']}")
            else:
                response_parts.append(f"\n📚 暂无关于 {name} 的印象记忆")
            
            # 组合响应
            response = "\n".join(response_parts)
            yield event.plain_result(response)
            
        except Exception as e:
            logger.error(f"查询印象失败: {e}")
            yield event.plain_result(f"查询 {name} 的印象时出现错误")
    
    @memory.command("图谱")
    async def memory_graph(self, event: AstrMessageEvent, layout_style: str = "auto"):
        """生成记忆图谱可视化图片
        
        Args:
            layout_style: 布局风格，可选值：
                - auto: 自适应布局（根据图的复杂度自动选择最适合的布局，默认）
                - force_directed: 力导向布局
                - circular: 圆形布局
                - kamada_kawai: Kamada-Kawai布局
                - spectral: 谱布局
                - community: 社区布局
                - hierarchical: 多层次布局
        """
        # 检查记忆系统是否启用
        if not self.memory_system.config_manager.is_memory_system_enabled():
            yield event.plain_result("记忆系统已禁用，无法生成图谱。")
            return
            
        try:
            # 发送生成中的提示
            yield event.plain_result(f"🔄 正在生成记忆图谱（布局风格: {layout_style}），请稍候...")
            
            # 异步生成图谱图片
            image_path = await self.graph_visualizer.generate_graph_image(layout_style=layout_style)
            
            if image_path:
                # 检查文件是否存在
                if os.path.exists(image_path):
                    # 发送图片消息
                    try:
                        # 尝试使用 AstrBot 的图片发送功能
                        if hasattr(event, 'send_image'):
                            await event.send_image(image_path)
                            yield event.plain_result(f"✅ 记忆图谱已生成！（布局风格: {layout_style}）")
                        else:
                            # 如果不支持直接发送图片，尝试使用其他方法
                            yield event.image_result(image_path)
                    except Exception as img_e:
                        logger.error(f"发送图片失败: {img_e}", exc_info=True)
                        # 如果发送图片失败，发送文件路径
                        yield event.plain_result(f"✅ 记忆图谱已生成！（布局风格: {layout_style}）\n图片路径: {image_path}")
                else:
                    yield event.plain_result("❌ 图谱文件生成失败，请检查权限和磁盘空间。")
            else:
                yield event.plain_result("❌ 记忆图谱生成失败，可能是因为：\n1. 未安装依赖库（networkx, matplotlib）\n2. 记忆数据为空\n3. 系统错误")
                
        except Exception as e:
            logger.error(f"生成记忆图谱失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 生成记忆图谱时出现错误: {str(e)}")
    
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """监听所有消息，形成记忆并注入相关记忆"""
        if not self._initialized:
            self._debug_log("记忆系统尚未初始化完成，跳过消息处理", "debug")
            return
        # 检查记忆系统是否启用
        if not self.memory_system.config_manager.is_memory_system_enabled():
            return
            
        try:
            # 提取群聊ID，用于群聊隔离
            group_id = event.get_group_id() if event.get_group_id() else ""
            
            # 1. 为当前群聊加载相应的记忆状态（异步优化）
            if group_id and self.memory_system.memory_config.get("enable_group_isolation", True):
                # 清空当前记忆图，重新加载群聊特定的记忆
                self.memory_system.memory_graph = MemoryGraph()
                self.memory_system.load_memory_state(group_id)
            
            # 2. 注入相关记忆到上下文（快速异步操作）
            self.memory_system._create_managed_task(self.memory_system.inject_memories_to_context(event))
            
            # 3. 消息处理使用异步队列，避免阻塞主流程
            self.memory_system._create_managed_task(self._process_message_async(event, group_id))
                
        except Exception as e:
            self._debug_log(f"on_message处理错误: {e}", "error")
    
    async def _process_message_async(self, event: AstrMessageEvent, group_id: str):
        """异步消息处理，避免阻塞主流程"""
        try:
            # 使用优化后的单次LLM调用处理消息
            await self.memory_system.process_message_optimized(event, group_id)
            
            # 使用队列化保存，减少I/O操作
            if group_id and self.memory_system.memory_config.get("enable_group_isolation", True):
                await self.memory_system._queue_save_memory_state(group_id)
            else:
                await self.memory_system._queue_save_memory_state("")  # 默认数据库
                
        except Exception as e:
            self._debug_log(f"异步消息处理失败: {e}", "error")

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """处理LLM请求时的记忆召回"""
        try:
            if not self._initialized:
                return
                
            # 获取当前消息内容
            current_message = event.message_str.strip()
            if not current_message:
                return
            
            # 使用增强记忆召回系统
            enhanced_recall = EnhancedMemoryRecall(self.memory_system)
            results = await enhanced_recall.recall_all_relevant_memories(
                query=current_message,
                max_memories=self.memory_system.memory_config.get("max_injected_memories", 5)
            )
            
            if results:
                # 格式化记忆为上下文
                memory_context = enhanced_recall.format_memories_for_llm(results)
                
                # 将记忆注入到系统提示中
                if hasattr(req, 'system_prompt'):
                    original_prompt = req.system_prompt or ""
                    if "【相关记忆】" not in original_prompt:
                        req.system_prompt = f"{original_prompt}\n\n{memory_context}"
                        logger.debug(f"已注入 {len(results)} 条记忆到LLM上下文")
                        
        except Exception as e:
            logger.error(f"LLM请求记忆召回失败: {e}", exc_info=True)
    
    async def terminate(self):
        """插件卸载时保存记忆并清理资源"""
        self._debug_log("开始插件终止流程，清理所有资源", "info")
        
        try:
            # 1. 停止维护循环
            if hasattr(self.memory_system, '_should_stop_maintenance'):
                self.memory_system._should_stop_maintenance.set()
            if hasattr(self.memory_system, '_maintenance_task') and self.memory_system._maintenance_task:
                # 等待维护任务正常退出
                try:
                    await asyncio.wait_for(self.memory_system._maintenance_task, timeout=10.0)
                except asyncio.TimeoutError:
                    # 如果超时，取消任务
                    self.memory_system._maintenance_task.cancel()
                    try:
                        await self.memory_system._maintenance_task
                    except asyncio.CancelledError:
                        pass
                        
            # 2. 取消所有托管的异步任务
            if hasattr(self.memory_system, '_managed_tasks'):
                await self.memory_system._cancel_all_managed_tasks()
            
            # 3. 等待待处理的保存任务完成
            if hasattr(self.memory_system, '_pending_save_task') and self.memory_system._pending_save_task and not self.memory_system._pending_save_task.done():
                try:
                    await asyncio.wait_for(self.memory_system._pending_save_task, timeout=5.0)
                except asyncio.TimeoutError:
                    self.memory_system._pending_save_task.cancel()
                    try:
                        await self.memory_system._pending_save_task
                    except asyncio.CancelledError:
                        pass
                    
            # 4. 清理嵌入向量缓存
            if hasattr(self.memory_system, 'embedding_cache') and self.memory_system.embedding_cache:
                try:
                    await self.memory_system.embedding_cache.cleanup()
                except Exception as e:
                    logger.warning(f"清理嵌入向量缓存时出错: {e}")
        
            # 5. 保存记忆状态
            await self.memory_system.save_memory_state()
            
            # 6. 如果启用了群聊隔离，保存所有群聊数据库
            if self.memory_system.memory_config.get("enable_group_isolation", True):
                db_dir = os.path.dirname(self.memory_system.db_path)
                if os.path.exists(db_dir):
                    for filename in os.listdir(db_dir):
                        if filename.startswith("memory_group_") and filename.endswith(".db"):
                            group_id = filename[12:-3]
                            await self.memory_system.save_memory_state(group_id)
            
            # 7. 使用资源管理器清理所有资源
            resource_manager.cleanup()
            
            self._debug_log("记忆系统已保存并安全关闭", "info")
            
        except Exception as e:
            logger.error(f"插件终止过程中发生错误: {e}", exc_info=True)
            
    async def safe_cleanup(self):
        """安全清理方法，用于在 terminate 之外调用的情况"""
        await self.terminate()

    # ---------- 插件API ----------
    async def add_memory_api(self, content: str, theme: str, group_id: str = "", details: str = "", participants: str = "", location: str = "", emotion: str = "", tags: str = "") -> Optional[str]:
        """
        【API】添加一条记忆。
        :param content: 记忆的核心内容。
        :param theme: 记忆的主题或关键词，用逗号分隔。
        :param group_id: 群组ID，如果需要在特定群聊中操作。
        :param details: 记忆的详细信息。
        :param participants: 参与者，用逗号分隔。
        :param location: 相关地点。
        :param emotion: 情感色彩。
        :param tags: 标签，用逗号分隔。
        :return: 成功则返回记忆ID，否则返回None。
        """
        if not self._initialized or not self.memory_system.memory_system_enabled:
            logger.warning("API调用失败：记忆系统未启用或未初始化。")
            return None
        
        try:
            # 切换到正确的群聊上下文
            if group_id and self.memory_system.memory_config.get("enable_group_isolation", True):
                self.memory_system.memory_graph = MemoryGraph()
                self.memory_system.load_memory_state(group_id)

            concept_id = self.memory_system.memory_graph.add_concept(theme)
            memory_id = self.memory_system.memory_graph.add_memory(
                content=content,
                concept_id=concept_id,
                details=details,
                participants=participants,
                location=location,
                emotion=emotion,
                tags=tags,
                group_id=group_id
            )
            
            # 异步保存
            await self.memory_system._queue_save_memory_state(group_id)
            
            logger.info(f"通过API添加记忆成功: {memory_id}")
            return memory_id
        except Exception as e:
            logger.error(f"API add_memory_api 失败: {e}", exc_info=True)
            return None

    async def recall_memories_api(self, keyword: str, group_id: str = "") -> List[Dict[str, Any]]:
        """
        【API】根据关键词回忆相关记忆。
        :param keyword: 要查询的关键词。
        :param group_id: 群组ID，如果需要在特定群聊中操作。
        :return: 记忆对象字典的列表。
        """
        if not self._initialized or not self.memory_system.memory_system_enabled:
            logger.warning("API调用失败：记忆系统未启用或未初始化。")
            return []

        try:
            # 切换到正确的群聊上下文
            if group_id and self.memory_system.memory_config.get("enable_group_isolation", True):
                self.memory_system.memory_graph = MemoryGraph()
                self.memory_system.load_memory_state(group_id)

            memories = await self.memory_system.recall_memories_full(keyword)
            return [memory.__dict__ for memory in memories]
        except Exception as e:
            logger.error(f"API recall_memories_api 失败: {e}", exc_info=True)
            return []

    async def record_impression_api(self, person_name: str, summary: str, score: Optional[float], details: str = "", group_id: str = "") -> bool:
        """
        【API】记录对某个人的印象。
        :param person_name: 人物名称。
        :param summary: 印象摘要。
        :param score: 好感度分数 (0-1)。
        :param details: 详细信息。
        :param group_id: 群组ID。
        :return: 操作是否成功。
        """
        if not self._initialized or not self.memory_system.memory_system_enabled:
            logger.warning("API调用失败：记忆系统未启用或未初始化。")
            return False

        try:
            if group_id and self.memory_system.memory_config.get("enable_group_isolation", True):
                self.memory_system.memory_graph = MemoryGraph()
                self.memory_system.load_memory_state(group_id)

            memory_id = self.memory_system.record_person_impression(group_id, person_name, summary, score, details)
            await self.memory_system._queue_save_memory_state(group_id)
            return bool(memory_id)
        except Exception as e:
            logger.error(f"API record_impression_api 失败: {e}", exc_info=True)
            return False

    async def get_impression_summary_api(self, person_name: str, group_id: str = "") -> Optional[Dict[str, Any]]:
        """
        【API】获取对某个人的印象摘要。
        :param person_name: 人物名称。
        :param group_id: 群组ID。
        :return: 包含摘要信息的字典，或在找不到时返回None。
        """
        if not self._initialized or not self.memory_system.memory_system_enabled:
            logger.warning("API调用失败：记忆系统未启用或未初始化。")
            return None

        try:
            if group_id and self.memory_system.memory_config.get("enable_group_isolation", True):
                self.memory_system.memory_graph = MemoryGraph()
                self.memory_system.load_memory_state(group_id)

            return self.memory_system.get_person_impression_summary(group_id, person_name)
        except Exception as e:
            logger.error(f"API get_impression_summary_api 失败: {e}", exc_info=True)
            return None

    async def adjust_impression_score_api(self, person_name: str, delta: float, group_id: str = "") -> Optional[float]:
        """
        【API】调整对某个人的好感度分数。
        :param person_name: 人物名称。
        :param delta: 好感度调整量，可正可负。
        :param group_id: 群组ID。
        :return: 调整后的新分数，或在失败时返回None。
        """
        if not self._initialized or not self.memory_system.memory_system_enabled:
            logger.warning("API调用失败：记忆系统未启用或未初始化。")
            return None

        try:
            if group_id and self.memory_system.memory_config.get("enable_group_isolation", True):
                self.memory_system.memory_graph = MemoryGraph()
                self.memory_system.load_memory_state(group_id)

            new_score = self.memory_system.adjust_impression_score(group_id, person_name, delta)
            await self.memory_system._queue_save_memory_state(group_id)
            return new_score
        except Exception as e:
            logger.error(f"API adjust_impression_score_api 失败: {e}", exc_info=True)
            return None

    # ---------- LLM 函数工具 ----------
    @filter.llm_tool(name="create_memory")
    async def create_memory_tool(
        self,
        event: AstrMessageEvent,
        content: str,
        theme: str = None,
        topic: str = None,
        details: str = "",
        participants: str = "",
        location: str = "",
        emotion: str = "",
        tags: str = "",
        confidence: str = "0.7"
    ) -> MessageEventResult:
        """通过LLM调用获取个记忆点和主题

        Args:
            content(string): 需要记录的完整对话内容
            theme(string): 核心关键词，用逗号分隔
            topic(string): 该记忆所属的主题或关键词（向后兼容）
            details(string): 具体细节和背景信息
            participants(string): 涉及的人物，用逗号分隔。特别注意：如果是Bot的发言，请使用"我"作为参与者
            location(string): 相关场景或地点
            emotion(string): 情感色彩，如"开心,兴奋"
            tags(string): 分类标签，如"工作,重要"
            confidence(number): 置信度，0-1之间的数值
        """
        try:
            # 向后兼容性处理：如果提供了topic但没有theme，使用topic作为theme
            actual_theme = theme or topic
            if not actual_theme:
                logger.warning("创建记忆失败：主题为空")
                
                return "创建记忆失败：主题为空"
            
            # 参数验证和清理
            if not content:
                logger.warning("创建记忆失败：内容为空")
                
                return "创建记忆失败：内容为空"
            
            # 清理特殊字符
            import re
            actual_theme = re.sub(r'[^\w\u4e00-\u9fff,，]', '', str(actual_theme))
            details = str(details).strip()
            participants = str(participants).strip()
            location = str(location).strip()
            emotion = str(emotion).strip()
            tags = str(tags).strip()
            
            # 将confidence从字符串转换为浮点数
            try:
                confidence_float = max(0.0, min(1.0, float(confidence)))
            except (ValueError, TypeError):
                logger.warning(f"无法将confidence '{confidence}' 转换为浮点数，使用默认值0.7")
                confidence_float = 0.7
            
            # 创建概念
            concept_id = self.memory_system.memory_graph.add_concept(actual_theme)
            
            # 根据置信度调整记忆强度
            base_strength = 1.0
            adjusted_strength = base_strength * confidence_float
            
            # 获取群组ID
            group_id = self.memory_system._extract_group_id_from_event(event)
            
            # 创建丰富记忆
            memory_id = self.memory_system.memory_graph.add_memory(
                content=content,
                concept_id=concept_id,
                details=details,
                participants=participants,
                location=location,
                emotion=emotion,
                tags=tags,
                strength=adjusted_strength
            )
            
            logger.info(f"LLM工具创建丰富记忆：{actual_theme} -> {content} (置信度: {confidence})")
            
            # 返回空字符串让LLM继续其自然回复流程
            return f"记忆创建成功,内容为:{content}"
            
        except Exception as e:
            logger.error(f"LLM工具创建记忆失败：{e}")
            await event.send(MessageChain().message("记忆创建失败"))
            return "记忆创建失败"

    @filter.llm_tool(name="recall_memory")
    async def recall_memory_tool(self, event: AstrMessageEvent, keyword: str) -> MessageEventResult:
        """召回所有相关记忆，包括联想记忆。

        Args:
            keyword(string): 要查询的关键词或内容
        """
        try:
            enhanced_recall = EnhancedMemoryRecall(self.memory_system)
            results = await enhanced_recall.recall_all_relevant_memories(
                query=keyword,
                max_memories=8
            )
            
            if results:
                # 生成增强的上下文
                formatted_memories = enhanced_recall.format_memories_for_llm(results)
                return f"记忆召回结果:{formatted_memories}"
            else:
                # 返回空字符串让LLM继续其自然回复流程
                return "没有相关记忆"
                  
        except Exception as e:
            logger.error(f"增强记忆召回工具失败：{e}")
            await event.send(MessageChain().message("记忆召回失败"))
            return "记忆召回失败"

    @filter.llm_tool(name="adjust_impression")
    async def adjust_impression_tool(
        self,
        event: AstrMessageEvent,
        person_name: str,
        delta: str,
        reason: str = ""
    ) -> MessageEventResult:
        """调整对某人的印象和好感度

        Args:
            person_name(string): 人物名称
            delta(number): 好感度调整量，可正可负
            reason(string): 调整原因和详细信息
        """
        try:
            # 获取群组ID
            group_id = self.memory_system._extract_group_id_from_event(event)
            
            # 调整印象分数 - 将字符串转换为浮点数
            try:
                delta_float = float(delta)
            except (ValueError, TypeError):
                logger.warning(f"无法将delta '{delta}' 转换为浮点数，使用默认值0.0")
                delta_float = 0.0
            
            new_score = self.memory_system.adjust_impression_score(group_id, person_name, delta_float)
            
            # 记录调整原因
            if reason:
                summary = f"调整对{person_name}的印象：{reason}，当前好感度：{new_score:.2f}"
                self.memory_system.record_person_impression(group_id, person_name, summary, new_score, reason)
            
            logger.info(f"LLM工具调整印象：{person_name} 调整量:{delta} 新分数:{new_score:.2f}")
            
            # 返回空字符串让LLM继续其自然回复流程
            return f"调整印象成功，{person_name} 的好感度为 {new_score:.2f}"
            
        except Exception as e:
            logger.error(f"LLM工具调整印象失败：{e}")
            await event.send(MessageChain().message("调整印象失败"))
            return "调整印象失败"

    @filter.llm_tool(name="record_impression")
    async def record_impression_tool(
        self,
        event: AstrMessageEvent,
        person_name: str,
        summary: str,
        score: str = None,
        details: str = ""
    ) -> MessageEventResult:
        """记录或更新对某人的印象

        Args:
            person_name(string): 人物名称
            summary(string): 印象摘要描述
            score(number): 好感度分数 (0-1)，可选
            details(string): 详细信息和背景
        """
        try:
            # 获取群组ID
            group_id = self.memory_system._extract_group_id_from_event(event)
            
            # 验证分数范围 - 将字符串转换为浮点数
            score_float = None
            if score is not None:
                try:
                    score_float = max(0.0, min(1.0, float(score)))
                except (ValueError, TypeError):
                    logger.warning(f"无法将score '{score}' 转换为浮点数，使用默认值")
                    score_float = None
            
            # 记录印象
            memory_id = self.memory_system.record_person_impression(
                group_id, person_name, summary, score_float, details
            )
            
            if memory_id:
                current_score = self.memory_system.get_impression_score(group_id, person_name)
                logger.info(f"LLM工具记录印象：{person_name} 分数:{current_score:.2f} 摘要:{summary[:50]}...")
            
            # 返回空字符串让LLM继续其自然回复流程
            return f"记录印象成功，{person_name} 的好感度为 {current_score:.2f}"
            
        except Exception as e:
            logger.error(f"LLM工具记录印象失败：{e}")
            await event.send(MessageChain().message("记录印象失败"))
            return "记录印象失败"


class MemorySystemConfig:
    """记忆系统配置数据类"""
    def __init__(self, enable_memory_system: bool = True):
        self.enable_memory_system = enable_memory_system
    
    @classmethod
    def from_dict(cls, config_dict):
        """从字典创建配置对象"""
        return cls(
            enable_memory_system=config_dict.get('enable_memory_system', True)
        )
    
    def to_dict(self):
        """转换为字典"""
        return {
            'enable_memory_system': self.enable_memory_system
        }

class MemoryConfigManager:
    """记忆系统配置管理器"""
    
    def __init__(self, config=None):
        """
        初始化配置管理器
        
        Args:
            config: 配置字典，如果为None则使用默认配置
        """
        if config is None:
            config = {}
        
        # 从配置中提取记忆系统相关配置
        memory_config_dict = {}
        
        # 处理主开关
        if 'enable_memory_system' in config:
            memory_config_dict['enable_memory_system'] = bool(config['enable_memory_system'])
        
        # 创建配置对象
        self.config = MemorySystemConfig.from_dict(memory_config_dict)
        
        logger.info(f"记忆系统配置管理器初始化完成，主开关: {'开启' if self.config.enable_memory_system else '关闭'}")
    
    def is_memory_system_enabled(self):
        """
        检查记忆系统是否启用
        
        Returns:
            bool: 记忆系统是否启用
        """
        return self.config.enable_memory_system
    
    def set_memory_system_enabled(self, enabled):
        """
        设置记忆系统启用状态
        
        Args:
            enabled: 是否启用记忆系统
        """
        self.config.enable_memory_system = enabled
        logger.info(f"记忆系统主开关设置为: {'开启' if enabled else '关闭'}")
    
    def get_config(self):
        """
        获取当前配置对象
        
        Returns:
            MemorySystemConfig: 当前配置对象
        """
        return self.config
    
    def update_config(self, config_dict):
        """
        更新配置
        
        Args:
            config_dict: 新的配置字典
        """
        old_enabled = self.config.enable_memory_system
        
        # 更新配置
        self.config = MemorySystemConfig.from_dict(config_dict)
        
        # 记录配置变更
        if old_enabled != self.config.enable_memory_system:
            logger.info(f"记忆系统主开关变更: {'开启' if self.config.enable_memory_system else '关闭'}")
    
    def get_config_dict(self):
        """
        获取配置字典
        
        Returns:
            Dict[str, Any]: 配置字典
        """
        return self.config.to_dict()
    
    def validate_config(self):
        """
        验证配置是否有效
        
        Returns:
            bool: 配置是否有效
        """
        try:
            # 检查主开关是否为布尔值
            if not isinstance(self.config.enable_memory_system, bool):
                logger.error("enable_memory_system 必须是布尔值")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"配置验证失败: {e}")
            return False

class MemorySystem:
    """核心记忆系统，模仿人类海马体功能"""
    
    @staticmethod
    def filter_memories_by_group(memories: List['Memory'], group_id: str = "") -> List['Memory']:
        """
        统一的群聊隔离过滤函数
        
        Args:
            memories: 记忆列表
            group_id: 群组ID，如果为空字符串则获取默认记忆
            
        Returns:
            过滤后的记忆列表
        """
        if not group_id:
            # 私聊场景：只获取没有group_id的记忆
            return [m for m in memories if not hasattr(m, 'group_id') or not m.group_id]
        else:
            # 群聊场景：只获取匹配group_id的记忆
            return [m for m in memories if hasattr(m, 'group_id') and m.group_id == group_id]
    
    @staticmethod
    def filter_concepts_by_group(concepts: Dict[str, 'Concept'], memories: Dict[str, 'Memory'], group_id: str = "") -> Dict[str, 'Concept']:
        """
        根据群聊隔离过滤概念
        
        Args:
            concepts: 概念字典
            memories: 记忆字典（用于判断概念是否属于指定群组）
            group_id: 群组ID
            
        Returns:
            过滤后的概念字典
        """
        filtered_concepts = {}
        
        for concept_id, concept in concepts.items():
            # 检查该概念下是否有属于指定群组的记忆
            concept_has_group_memory = False
            for memory in memories.values():
                if memory.concept_id == concept_id:
                    if not group_id and (not hasattr(memory, 'group_id') or not memory.group_id):
                        # 私聊场景：概念有无group_id的记忆
                        concept_has_group_memory = True
                        break
                    elif group_id and hasattr(memory, 'group_id') and memory.group_id == group_id:
                        # 群聊场景：概念有匹配group_id的记忆
                        concept_has_group_memory = True
                        break
            
            if concept_has_group_memory:
                filtered_concepts[concept_id] = concept
        
        return filtered_concepts
    
    def __init__(self, context: Context, config=None, data_dir=None):
        self.context = context
        
        # 初始化配置管理器
        self.config_manager = MemoryConfigManager(config)
        
        # 检查记忆系统是否启用
        if not self.config_manager.is_memory_system_enabled():
            logger.info("记忆系统已禁用，跳过初始化")
            self.memory_system_enabled = False
            return
        
        self.memory_system_enabled = True
        
        # 使用AstrBot标准数据目录
        if data_dir:
            self.db_path = str(data_dir / "memory.db")
        else:
            data_dir = StarTools.get_data_dir() / "memora_connect"
            self.db_path = str(data_dir / "memory.db")
        
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        logger.info(f"记忆数据库路径: {self.db_path}")
        
        self.memory_graph = MemoryGraph()
        self.llm_provider = None
        self.embedding_provider = None
        self.batch_extractor = BatchMemoryExtractor(self)
        self.embedding_cache = None  # 嵌入向量缓存管理器
        
        # 印象系统配置
        self.impression_config = {
            "default_score": 0.5,
            "enable_impression_injection": config.get("enable_impression_injection", True),
            "min_score": 0.0,
            "max_score": 1.0
        }
        
        # 配置初始化
        self.memory_config = config or {}
        
        # 群聊隔离的数据库表前缀映射
        self.group_table_prefixes = {}
        
        # 日志限制计数器
        self.debug_log_count = 0
        self.debug_log_reset_time = time.time()
        
        # 优化：缓存和批量操作
        self._save_cache = {}  # 保存缓存 {group_id: pending_changes}
        self._save_locks = {}  # 保存锁 {group_id: asyncio.Lock}
        self._last_save_time = {}  # 最后保存时间 {group_id: timestamp}
        self._pending_save_task = None  # 待处理的保存任务
        
        # 异步任务生命周期管理 - 新增
        self._managed_tasks = set()  # 管理的异步任务集合
        self._maintenance_task = None  # 维护循环任务
        self._should_stop_maintenance = asyncio.Event()  # 停止维护事件
        self._should_stop_maintenance.clear()  # 初始不停止
        
    def _create_managed_task(self, coro):
        """创建托管的异步任务，确保任务生命周期被正确管理"""
        if not asyncio.iscoroutine(coro):
            self._debug_log(f"无法创建任务：传入的不是协程对象", "warning")
            return
        
        # 使用事件循环管理器创建任务
        task = resource_manager.create_task(coro)
        self._managed_tasks.add(task)
        
        self._debug_log(f"创建新任务: {coro.__name__}。当前任务数: {len(self._managed_tasks)}", "debug")
        # 添加任务完成回调，自动清理
        def _task_done_callback(t):
            self._managed_tasks.discard(t)
            if t.exception():
                self._debug_log(f"托管任务异常: {t.exception()}", "error")
            self._debug_log(f"任务 {coro.__name__} 完成。当前任务数: {len(self._managed_tasks)}", "debug")
        
        task.add_done_callback(_task_done_callback)
        return task
    
    async def _cancel_all_managed_tasks(self):
        """取消所有托管的异步任务"""
        if not self._managed_tasks:
            return
        
        # 取消所有任务
        for task in self._managed_tasks:
            if not task.done():
                task.cancel()
        
        # 等待所有任务完成或取消
        if self._managed_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._managed_tasks, return_exceptions=True),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                # 如果超时，强制清理
                self._managed_tasks.clear()
        
        self._debug_log("已清理所有托管任务", "debug")
        
    def _get_group_db_path(self, group_id: str) -> str:
        """获取群聊专用的数据库路径 - 统一使用主数据库，通过逻辑隔离实现群聊分离"""
        # 统一使用主数据库，通过 group_id 字段实现逻辑隔离
        return self.db_path
    
    def _extract_group_id_from_event(self, event: AstrMessageEvent) -> str:
        """从事件中提取群聊ID"""
        group_id = event.get_group_id()
        return group_id if group_id else ""
    
    async def _queue_save_memory_state(self, group_id: str = ""):
        """队列化保存操作，减少频繁的I/O"""
        try:
            # 获取或创建锁
            if group_id not in self._save_locks:
                self._save_locks[group_id] = asyncio.Lock()
            
            # 获取最后保存时间
            last_save = self._last_save_time.get(group_id, 0)
            current_time = time.time()
            
            # 如果距离上次保存时间少于2秒，延迟保存
            if current_time - last_save < 2:
                # 取消之前的保存任务
                if self._pending_save_task and not self._pending_save_task.done():
                    self._pending_save_task.cancel()
                
                # 创建新的延迟保存任务
                self._pending_save_task = asyncio.create_task(
                    self._delayed_save(group_id, current_time)
                )
            else:
                # 立即保存
                await self.save_memory_state(group_id)
                self._last_save_time[group_id] = current_time
                
        except Exception as e:
            self._debug_log(f"队列保存失败: {e}", "warning")
    
    async def _delayed_save(self, group_id: str, creation_time: float):
        """延迟保存任务"""
        try:
            # 延迟2秒执行
            await asyncio.sleep(2)
            
            # 检查是否还有新的保存请求
            if self._last_save_time.get(group_id, 0) > creation_time:
                return  # 如果有更新的请求，跳过这次保存
            
            # 执行实际保存
            await self.save_memory_state(group_id)
            self._last_save_time[group_id] = time.time()
            
        except asyncio.CancelledError:
            pass  # 任务被取消，正常情况
        except Exception as e:
            self._debug_log(f"延迟保存失败: {e}", "warning")
    

    # --- 插入的新方法:获取真实历史长度 ---
    async def _get_real_history_count(self, event: AstrMessageEvent) -> int:
        """获取未截断的真实对话历史总条数"""
        try:
            uid = event.unified_msg_origin
            curr_cid = await self.context.conversation_manager.get_curr_conversation_id(uid)
            if curr_cid:
                conversation = await self.context.conversation_manager.get_conversation(uid, curr_cid)
                if conversation and conversation.history:
                    history_list = json.loads(conversation.history)
                    return len(history_list)
            return 0
        except Exception:
            return 0
    # -------------------------------------

    def _debug_log(self, message: str, level: str = "debug"):
        """优化的调试日志输出，限制日志频率"""
        current_time = time.time()
        
        # 每分钟重置计数器
        if current_time - self.debug_log_reset_time > 60:
            self.debug_log_count = 0
            self.debug_log_reset_time = current_time
        
        # 限制每分钟最多10条调试日志
        if level == "debug" and self.debug_log_count >= 10:
            return
        
        if level == "debug":
            self.debug_log_count += 1
        
        # 使用不同的日志级别
        if level == "debug":
            logger.debug(message)
        elif level == "info":
            logger.info(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "error":
            logger.error(message)
    
    async def initialize(self):
        """初始化记忆系统"""
        # 检查记忆系统是否启用
        if not self.memory_system_enabled:
            self._debug_log("记忆系统已禁用，跳过初始化", "info")
            return
        
        self._debug_log("开始初始化记忆系统...", "info")
        
        # 检查默认数据库文件状态
        if os.path.exists(self.db_path):
            file_size = os.path.getsize(self.db_path)
            self._debug_log(f"默认数据库文件存在，大小: {file_size} 字节", "info")
        else:
            self._debug_log("默认数据库文件不存在，将创建新数据库", "info")
        
        # 测试提供商连接 - 简化为单一日志
        llm_ready = False
        embedding_ready = False
        
        try:
            llm_provider = await self.get_llm_provider()
            if llm_provider:
                llm_ready = True
                
            embedding_provider = await self.get_embedding_provider()
            if embedding_provider:
                embedding_ready = True
                
            self._debug_log(f"提供商状态 - LLM: {'已连接' if llm_ready else '未连接'}, 嵌入: {'已连接' if embedding_ready else '未连接'}", "info")
        except Exception as e:
            self._debug_log("提供商连接异常，系统将继续运行", "warning")
        
        # 执行数据库迁移
        try:
            migration = SmartDatabaseMigration(self.db_path, self.context)
            
            # 1. 先执行主数据库迁移
            migration_success = await migration.run_smart_migration()
            
            if migration_success:
                self._debug_log("主数据库迁移成功", "info")
            else:
                self._debug_log("主数据库迁移失败，记忆系统可能无法正常工作", "error")
                
        except Exception as e:
            self._debug_log(f"主数据库迁移过程异常: {e}", "error")
            migration_success = False
        
        # 2. 执行嵌入向量缓存数据库迁移
        embedding_migration_success = False
        try:
            embedding_migration_success = await migration.run_embedding_cache_migration()
            if embedding_migration_success:
                self._debug_log("嵌入向量缓存数据库迁移成功", "info")
            else:
                self._debug_log("嵌入向量缓存数据库迁移失败", "warning")
        except Exception as embedding_e:
            self._debug_log(f"嵌入向量缓存数据库迁移异常: {embedding_e}", "warning")
        
        # 3. 只有在两个迁移都成功的情况下，才继续初始化
        if migration_success and embedding_migration_success:
            try:
                # 加载默认数据库（用于私有对话）
                self.load_memory_state()
                asyncio.create_task(self.memory_maintenance_loop())
                
                # 初始化嵌入向量缓存管理器
                self.embedding_cache = EmbeddingCacheManager(self, self.db_path)
                await self.embedding_cache.initialize()
                
                # 调度初始预计算任务
                if self.memory_graph.memories:
                    asyncio.create_task(self.embedding_cache.schedule_initial_precompute())
                    logger.info(f"已调度 {len(self.memory_graph.memories)} 条记忆的预计算任务")
                
                self._debug_log("记忆系统初始化完成", "info")
            except Exception as init_e:
                self._debug_log(f"记忆系统初始化失败: {init_e}", "error")
        else:
            self._debug_log("由于数据库迁移失败，跳过记忆系统初始化", "warning")
        
    def load_memory_state(self, group_id: str = ""):
        """从数据库加载记忆状态"""
        import os
        
        # 获取对应的数据库路径
        db_path = self._get_group_db_path(group_id)
        
        if not os.path.exists(db_path):
            return
            
        try:
            # 使用连接池获取数据库连接
            conn = resource_manager.get_db_connection(db_path)
            cursor = conn.cursor()
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='concepts'")
            if not cursor.fetchone():
                return
            
            # 加载概念
            cursor.execute("SELECT id, name, created_at, last_accessed, access_count FROM concepts")
            concepts = cursor.fetchall()
            for concept_data in concepts:
                self.memory_graph.add_concept(
                    concept_id=concept_data[0],
                    name=concept_data[1],
                    created_at=concept_data[2],
                    last_accessed=concept_data[3],
                    access_count=concept_data[4]
                )
                
            # 加载记忆 - 支持群聊隔离
            if group_id:
                cursor.execute("SELECT id, concept_id, content, details, participants, location, emotion, tags, created_at, last_accessed, access_count, strength FROM memories WHERE group_id = ?", (group_id,))
            else:
                cursor.execute("SELECT id, concept_id, content, details, participants, location, emotion, tags, created_at, last_accessed, access_count, strength FROM memories WHERE group_id = '' OR group_id IS NULL")
            memories = cursor.fetchall()
            for memory_data in memories:
                self.memory_graph.add_memory(
                    content=memory_data[2],
                    concept_id=memory_data[1],
                    memory_id=memory_data[0],
                    details=memory_data[3] or "",
                    participants=memory_data[4] or "",
                    location=memory_data[5] or "",
                    emotion=memory_data[6] or "",
                    tags=memory_data[7] or "",
                    created_at=memory_data[8],
                    last_accessed=memory_data[9],
                    access_count=memory_data[10],
                    strength=memory_data[11],
                    group_id=group_id
                )
                
            # 加载连接
            cursor.execute("SELECT id, from_concept, to_concept, strength, last_strengthened FROM connections")
            connections = cursor.fetchall()
            for conn_data in connections:
                self.memory_graph.add_connection(
                    from_concept=conn_data[1],
                    to_concept=conn_data[2],
                    strength=conn_data[3],
                    connection_id=conn_data[0],
                    last_strengthened=conn_data[4]
                )
                
            # 释放连接回连接池
            resource_manager.release_db_connection(db_path, conn)
                
            # 仅在成功加载时输出一次统计信息
            group_info = f" (群: {group_id})" if group_id else ""
            self._debug_log(f"记忆系统加载{group_info}，包含 {len(concepts)} 个概念，{len(memories)} 条记忆", "debug")
            
        except Exception as e:
            self._debug_log(f"状态加载异常: {e}", "error")

    async def save_memory_state(self, group_id: str = ""):
        """保存记忆状态到数据库"""
        try:
            # 获取对应的数据库路径
            db_path = self._get_group_db_path(group_id)
            
            # 确保数据库和表存在
            await self._ensure_database_structure(db_path)
            
            # 使用连接池获取数据库连接
            conn = resource_manager.get_db_connection(db_path)
            cursor = conn.cursor()
            
            # 使用事务确保数据一致性
            cursor.execute("BEGIN TRANSACTION")
            
            try:
                
                # 增量更新概念
                for concept in self.memory_graph.concepts.values():
                    cursor.execute('''
                        INSERT OR REPLACE INTO concepts
                        (id, name, created_at, last_accessed, access_count)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (concept.id, concept.name, concept.created_at, concept.last_accessed, concept.access_count))
                
                # 增量更新记忆
                for memory in self.memory_graph.memories.values():
                    cursor.execute('''
                        INSERT OR REPLACE INTO memories
                        (id, concept_id, content, details, participants,
                        location, emotion, tags, created_at, last_accessed, access_count, strength, group_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (memory.id, memory.concept_id, memory.content, memory.details,
                         memory.participants, memory.location, memory.emotion, memory.tags,
                         memory.created_at, memory.last_accessed, memory.access_count, memory.strength, group_id))
                
                # 增量更新连接
                existing_connections = set()
                cursor.execute("SELECT id FROM connections")
                for row in cursor.fetchall():
                    existing_connections.add(row[0])
                
                # 更新现有连接
                for conn_obj in self.memory_graph.connections:
                    if conn_obj.id in existing_connections:
                        cursor.execute('''
                            UPDATE connections
                            SET from_concept=?, to_concept=?, strength=?, last_strengthened=?
                            WHERE id=?
                        ''', (conn_obj.from_concept, conn_obj.to_concept, conn_obj.strength, conn_obj.last_strengthened, conn_obj.id))
                    else:
                        cursor.execute('''
                            INSERT INTO connections (id, from_concept, to_concept, strength, last_strengthened)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (conn_obj.id, conn_obj.from_concept, conn_obj.to_concept, conn_obj.strength, conn_obj.last_strengthened))
                
                # 提交事务
                conn.commit()
                
                # 释放连接回连接池
                resource_manager.release_db_connection(db_path, conn)
                
                # 简化的保存完成日志
                group_info = f" (群: {group_id})" if group_id else ""
                self._debug_log(f"记忆保存完成{group_info}: {len(self.memory_graph.concepts)}个概念, {len(self.memory_graph.memories)}条记忆", "debug")
                
            except Exception as e:
                try:
                    # 回滚事务
                    conn.rollback()
                except Exception as rollback_e:
                    self._debug_log(f"回滚失败: {rollback_e}", "error")
                # 释放连接回连接池
                resource_manager.release_db_connection(db_path, conn)
                self._debug_log(f"保存失败: {e}", "error")
                raise
                
        except Exception as e:
            self._debug_log(f"保存过程异常: {e}", "error")
    
    async def _ensure_database_structure(self, db_path: str):
        """确保数据库和所需的表结构存在"""
        try:
            # 使用连接池获取数据库连接
            conn = resource_manager.get_db_connection(db_path)
            cursor = conn.cursor()
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing_tables = {row[0] for row in cursor.fetchall()}
            
            # 创建所需的表（如果不存在）
            if 'concepts' not in existing_tables:
                cursor.execute('''
                    CREATE TABLE concepts (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        created_at REAL,
                        last_accessed REAL,
                        access_count INTEGER DEFAULT 0
                    )
                ''')
                self._debug_log(f"创建表: concepts", "debug")
            
            if 'memories' not in existing_tables:
                cursor.execute('''
                    CREATE TABLE memories (
                        id TEXT PRIMARY KEY,
                        concept_id TEXT NOT NULL,
                        content TEXT NOT NULL,
                        details TEXT,
                        participants TEXT,
                        location TEXT,
                        emotion TEXT,
                        tags TEXT,
                        created_at REAL,
                        last_accessed REAL,
                        access_count INTEGER DEFAULT 0,
                        strength REAL DEFAULT 1.0,
                        group_id TEXT DEFAULT "",
                        FOREIGN KEY (concept_id) REFERENCES concepts (id)
                    )
                ''')
                self._debug_log(f"创建表: memories", "debug")
                
                # 创建群聊隔离相关的索引
                cursor.execute('''
                    CREATE INDEX idx_memories_group_id ON memories(group_id)
                ''')
                cursor.execute('''
                    CREATE INDEX idx_memories_concept_group ON memories(concept_id, group_id)
                ''')
                cursor.execute('''
                    CREATE INDEX idx_memories_created_group ON memories(created_at, group_id)
                ''')
                self._debug_log(f"创建群聊隔离索引", "debug")
            
            if 'connections' not in existing_tables:
                cursor.execute('''
                    CREATE TABLE connections (
                        id TEXT PRIMARY KEY,
                        from_concept TEXT NOT NULL,
                        to_concept TEXT NOT NULL,
                        strength REAL DEFAULT 1.0,
                        last_strengthened REAL,
                        FOREIGN KEY (from_concept) REFERENCES concepts (id),
                        FOREIGN KEY (to_concept) REFERENCES concepts (id)
                    )
                ''')
                self._debug_log(f"创建表: connections", "debug")
            
            conn.commit()
            
            # 释放连接回连接池
            resource_manager.release_db_connection(db_path, conn)
                
        except Exception as e:
            self._debug_log(f"确保数据库结构异常: {e}", "error")
            raise
    
    async def process_message(self, event: AstrMessageEvent, group_id: str = ""):
        """处理消息，形成记忆（旧方法，保留兼容性）"""
        try:
            # 获取对话历史
            history = await self.get_conversation_history(event)
            if not history:
                return
                
            # 提取主题和关键词
            themes = await self.extract_themes(history)
            
            # 形成记忆
            for theme in themes:
                memory_content = await self.form_memory(theme, history, event)
                if memory_content:
                    concept_id = self.memory_graph.add_concept(theme)
                    memory_id = self.memory_graph.add_memory(memory_content, concept_id, group_id=group_id)
                    
                    # 建立连接
                    self.establish_connections(concept_id, themes)
                    
            # 根据回忆模式决定是否触发回忆
            recall_mode = self.memory_config["recall_mode"]
            should_trigger = False
            
            if recall_mode == "simple" or recall_mode == "embedding":
                # 关键词和嵌入模式每次都触发
                should_trigger = True
            elif recall_mode == "llm":
                # LLM模式按概率触发
                trigger_probability = self.memory_config.get("recall_trigger_probability", 0.6)
                should_trigger = random.random() < trigger_probability
            
            if should_trigger:
                recalled = await self.recall_memories("", event)
                if recalled:
                    logger.debug(f"触发了回忆: {recalled[:2]} (模式: {recall_mode})")
                    
        except Exception as e:
            logger.error(f"处理消息时出错: {e}")

    async def process_message_optimized(self, event: AstrMessageEvent, group_id: str = ""):
        """优化的消息处理,使用单次LLM调用(包含 BUG 修复)"""
        try:
            # 1. 核心修复:基于真实长度判断间隔
            real_count = await self._get_real_history_count(event)
            memory_formation_interval = self.memory_config.get("memory_formation_interval", 15)

            if real_count == 0 or real_count % memory_formation_interval != 0:
                return

            # 2. 获取用于提取的截断后历史 (供LLM使用)
            full_history = await self.get_conversation_history_full(event)
            if not full_history:
                return

            # 3. 检查是否启用批量记忆提取
            enable_batch_extraction = self.memory_config.get("enable_batch_memory_extraction", True)
            if not enable_batch_extraction:
                return

            # 4. 使用批量提取器
            extracted_memories = await self.batch_extractor.extract_memories_and_themes(full_history)

            if not extracted_memories:
                return

            # 5. 批量处理提取的记忆
            themes = []
            concept_ids = []
            valid_memories = 0

            for memory_data in extracted_memories:
                try:
                    theme = str(memory_data.get("theme", "")).strip()
                    content = str(memory_data.get("content", "")).strip()
                    details = str(memory_data.get("details", "")).strip()
                    participants = str(memory_data.get("participants", "")).strip()
                    location = str(memory_data.get("location", "")).strip()
                    emotion = str(memory_data.get("emotion", "")).strip()
                    tags = str(memory_data.get("tags", "")).strip()
                    confidence = float(memory_data.get("confidence", 0.7))
                    memory_type = str(memory_data.get("memory_type", "normal")).strip().lower()

                    if not theme or not content:
                        continue

                    base_strength = 1.0
                    adjusted_strength = base_strength * max(0.0, min(1.0, confidence))

                    if memory_type == "impression":
                        person_name = self._extract_person_name_from_theme(theme)
                        if person_name:
                            self.record_person_impression(group_id, person_name, content, adjusted_strength, details)
                            continue

                    if memory_type == "normal":
                        concept_id = self.memory_graph.add_concept(theme)
                        self.memory_graph.add_memory(
                            content=content,
                            concept_id=concept_id,
                            details=details,
                            participants=participants,
                            location=location,
                            emotion=emotion,
                            tags=tags,
                            strength=adjusted_strength,
                            group_id=group_id
                        )
                        themes.append(theme)
                        concept_ids.append(concept_id)
                        valid_memories += 1

                except Exception:
                    continue

            if valid_memories > 0:
                group_info = f" (群: {group_id})" if group_id else ""
                self._debug_log(f"批量创建记忆{group_info}: {valid_memories}条", "debug")

            if concept_ids:
                for concept_id in concept_ids:
                    try:
                        self.establish_connections(concept_id, themes)
                    except Exception:
                        continue

            if self.impression_config.get("enable_impression_injection", True):
                try:
                    llm_provider = await self.get_llm_provider()
                    if llm_provider:
                        extracted_impressions = await self.batch_extractor.extract_impressions_from_conversation(full_history, group_id)
                        if extracted_impressions:
                            for imp in extracted_impressions:
                                self.record_person_impression(
                                    group_id, imp['person_name'], imp['summary'], imp['score'], imp['details']
                                )
                        else:
                            await self._fallback_impression_extraction(full_history, group_id)

                except Exception as e:
                    self._debug_log(f"印象提取失败: {e}", "warning")
        except Exception as e:
            self._debug_log(f"优化消息处理失败: {e}", "error")


    async def _fallback_impression_extraction(self, conversation_history: List[Dict[str, Any]], group_id: str):
        """基于关键词的简单印象提取（备用方案）"""
        try:
            impression_keywords = {
                "觉得": 0.1, "感觉": 0.1, "印象": 0.2,
                "人不错": 0.3, "挺好的": 0.2, "很厉害": 0.3,
                "有点": -0.1, "不太行": -0.3, "很差": -0.4
            }
            
            for msg in conversation_history:
                content = msg.get("content", "")
                sender_name = msg.get("sender_name", "用户")
                
                # 提取潜在人名
                mentioned_names = self._extract_mentioned_names(content)
                
                for name in mentioned_names:
                    if name == sender_name or name == "我":
                        continue
                        
                    for keyword, score_delta in impression_keywords.items():
                        if keyword in content:
                            # 找到了一个关于某个人的印象
                            summary = f"感觉 {name} {keyword}"
                            self.record_person_impression(group_id, name, summary, score=None, details=f"来自 {sender_name} 的评价: {content}")
                            self.adjust_impression_score(group_id, name, score_delta)
                            self._debug_log(f"备用方案提取印象: {name} ({keyword})", "debug")
                            
        except Exception as e:
            self._debug_log(f"备用印象提取方案失败: {e}", "warning")
    
    async def get_conversation_history(self, event: AstrMessageEvent) -> List[str]:
        """获取对话历史（兼容旧版本）"""
        try:
            uid = event.unified_msg_origin
            curr_cid = await self.context.conversation_manager.get_curr_conversation_id(uid)
            if curr_cid:
                conversation = await self.context.conversation_manager.get_conversation(uid, curr_cid)
                if conversation and conversation.history:
                    history = json.loads(conversation.history)
                    return [msg.get("content", "") for msg in history[-10:]]  # 最近10条
            return []
        except Exception as e:
            logger.error(f"获取对话历史失败: {e}")
            return []

    async def get_conversation_history_full(self, event: AstrMessageEvent) -> List[Dict[str, Any]]:
        """获取包含完整信息的对话历史"""
        try:
            uid = event.unified_msg_origin
            curr_cid = await self.context.conversation_manager.get_curr_conversation_id(uid)
            if curr_cid:
                conversation = await self.context.conversation_manager.get_conversation(uid, curr_cid)
                if conversation and conversation.history:
                    history = json.loads(conversation.history)
                    # 添加发送者信息和时间戳
                    full_history = []
                    # 从配置中获取对话历史条数，默认为20条
                    conversation_history_count = self.memory_config.get("conversation_history_count", 20)
                    for msg in history[-conversation_history_count:]:  # 使用配置中的条数，避免token过多
                        full_msg = {
                            "role": msg.get("role", "user"),
                            "content": msg.get("content", ""),
                            "sender_name": msg.get("sender_name", "用户"),
                            "timestamp": msg.get("timestamp", time.time())
                        }
                        full_history.append(full_msg)
                    return full_history
            return []
        except Exception as e:
            logger.error(f"获取完整对话历史失败: {e}")
            return []
    
    async def extract_themes(self, history: List[str]) -> List[str]:
        """从对话历史中提取主题"""
        if not history:
            return []
            
        # 根据配置选择提取方式
        if self.memory_config["recall_mode"] in ["llm", "embedding"]:
            return await self._extract_themes_by_llm(history)
        else:
            return await self._extract_themes_simple(history)
    
    async def _extract_themes_simple(self, history: List[str]) -> List[str]:
        """简单的关键词提取"""
        text = " ".join(str(item) if not isinstance(item, str) else item for item in history)
        keywords = []
        
        # 提取名词和关键词
        words = re.findall(r'\b[\u4e00-\u9fff]{2,4}\b', text)
        word_freq = {}
        for word in words:
            if len(word) >= 2 and word not in ["你好", "谢谢", "再见"]:
                word_freq[word] = word_freq.get(word, 0) + 1
        
        # 返回频率最高的前5个关键词
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [str(word) for word, freq in sorted_words[:5]]
    
    async def _extract_themes_by_llm(self, history: List[str]) -> List[str]:
        """使用LLM从对话历史中提取主题"""
        try:
            if not history:
                return []
                
            prompt = f"""请从以下对话中提取3-5个核心主题或关键词。这些主题将用于构建记忆网络。

对话内容：
{" ".join(map(str, history))}

要求：
1. 提取的主题应该是对话的核心内容
2. 每个主题可以包含多个相关关键词，用逗号分隔
3. 返回格式：主题1关键词1,主题1关键词2,主题2关键词1,主题2关键词2
4. 每个关键词2-4个汉字
5. 不要包含解释，只返回主题列表
6. 例如：工作,项目,会议,学习,考试,复习
"""
            
            provider = await self.get_llm_provider()
            if provider:
                response = await provider.text_chat(
                    prompt=prompt,
                    contexts=[],
                    system_prompt="你是一个主题提取助手，请准确提取对话的核心主题。"
                )
                
                themes_text = response.completion_text.strip()
                # 清理和分割主题，支持逗号分隔的多个关键词
                themes = [theme.strip() for theme in themes_text.replace("，", ",").split(",") if theme.strip()]
                return themes[:8]  # 最多返回8个关键词/主题
                
        except Exception as e:
            logger.error(f"LLM主题提取失败: {e}")
            return await self._extract_themes_simple(history)  # 回退到简单模式
    
    async def form_memory(self, theme: str, history: List[str], event: AstrMessageEvent) -> str:
        """形成记忆内容"""
        try:
            # 使用LLM总结记忆
            prompt = f"""请将以下关于"{theme}"的对话总结成一句口语化的记忆，就像亲身经历一样：
            
            对话内容：{" ".join(map(str, history[-3:]))}
            
            要求：
            1. 如果记忆内容涉及Bot的发言，请使用第一人称"我"来表述
            2. 如果记忆内容涉及用户的发言，请使用第三人称
            3. 简洁自然
            4. 包含关键信息
            5. 不超过50字
            """
            
            if self.memory_config["recall_mode"] == "llm":
                provider = await self.get_llm_provider()
                if provider:
                    response = await provider.text_chat(
                        prompt=prompt,
                        contexts=[],
                        system_prompt=self.memory_config["llm_system_prompt"]
                    )
                    return response.completion_text.strip()
            
            # 简单总结
            return f"我记得我们聊过关于{theme}的事情"
                
        except Exception as e:
            logger.error(f"形成记忆失败: {e}")
            return f"关于{theme}的记忆"
    
    def establish_connections(self, concept_id: str, themes: List[str]):
        """建立概念之间的连接"""
        try:
            if concept_id not in self.memory_graph.concepts:
                logger.warning(f"概念ID不存在: {concept_id}")
                return
                
            current_concept = self.memory_graph.concepts[concept_id]
            
            for other_theme in themes:
                if other_theme != current_concept.name:
                    other_concept = None
                    for concept in self.memory_graph.concepts.values():
                        if concept.name == other_theme:
                            other_concept = concept
                            break
                    
                    if other_concept and other_concept.id != concept_id:
                        self.memory_graph.add_connection(concept_id, other_concept.id)
                        
        except Exception as e:
            logger.error(f"建立概念连接时出错: {e}, 概念ID: {concept_id}, 主题: {themes}")
    
    async def recall_memories_full(self, keyword: str) -> List['Memory']:
        """回忆相关记忆并返回完整的Memory对象"""
        try:
            # 这是一个简化的实现，用于演示目的
            # 在实际应用中，这里应该有更复杂的逻辑来匹配关键词
            related_memories = []
            keyword_lower = keyword.lower()

            for memory in self.memory_graph.memories.values():
                if keyword_lower in memory.content.lower():
                    related_memories.append(memory)
            
            return related_memories
                
        except Exception as e:
            logger.error(f"回忆记忆失败: {e}")
            return []

    async def _recall_simple(self, keyword: str) -> List[str]:
        """增强的简单关键词匹配回忆"""
        try:
            if not keyword:
                # 随机回忆，优先选择强度高的记忆
                memories = list(self.memory_graph.memories.values())
                if memories:
                    # 按记忆强度和时间排序
                    memories.sort(key=lambda m: (m.strength, m.last_accessed), reverse=True)
                    selected = memories[:min(3, len(memories))]
                    return [m.content for m in selected]
                return []
            
            # 增强的关键词匹配，支持多关键词匹配
            related_memories = []
            keyword_lower = keyword.lower()
            
            # 直接概念匹配，支持逗号分隔的多关键词
            for concept in self.memory_graph.concepts.values():
                concept_name_lower = concept.name.lower()
                
                # 检查概念名称是否包含任意关键词
                concept_keywords = concept_name_lower.split(',')
                for concept_keyword in concept_keywords:
                    concept_keyword = concept_keyword.strip()
                    if (keyword_lower in concept_keyword or concept_keyword in keyword_lower or
                        any(kw.strip() in concept_keyword for kw in keyword_lower.split(','))):
                        concept_memories = [m for m in self.memory_graph.memories.values()
                                          if m.concept_id == concept.id]
                        # 按记忆强度排序
                        concept_memories.sort(key=lambda m: m.strength, reverse=True)
                        for memory in concept_memories[:2]:  # 每个概念最多2条
                            if memory.content not in related_memories:
                                related_memories.append(memory.content)
                        break
            
            # 内容关键词匹配
            for memory in self.memory_graph.memories.values():
                if keyword_lower in memory.content.lower():
                    if memory.content not in related_memories:
                        related_memories.append(memory.content)
            
            # 去重并限制数量
            seen = set()
            unique_memories = []
            for memory in related_memories:
                if memory not in seen:
                    seen.add(memory)
                    unique_memories.append(memory)
                    if len(unique_memories) >= 5:
                        break
            
            return unique_memories
            
        except Exception as e:
            logger.error(f"简单回忆失败: {e}")
            return []

    async def _recall_llm(self, keyword: str, event: AstrMessageEvent) -> List[str]:
        """LLM智能回忆"""
        try:
            if not self.memory_graph.memories:
                return []
                
            # 获取所有记忆内容
            all_memories = [m.content for m in self.memory_graph.memories.values()]
            
            if not keyword:
                # 随机选择3条记忆
                return random.sample(all_memories, min(3, len(all_memories)))
            
            # 使用LLM进行智能回忆
            prompt = f"""请从以下记忆列表中，找出与用户提问“{keyword}”最相关的3-5条记忆。

记忆列表：
{chr(10).join(f"- {mem}" for mem in all_memories)}

严格按照以下JSON格式返回结果，不要有任何多余的解释：
{{
  "recalled_memories": [
    "记忆1",
    "记忆2",
    ...
  ]
}}

如果找不到任何相关记忆，或记忆列表为空，请返回一个空列表：
{{
  "recalled_memories": []
}}
"""

            provider = await self.get_llm_provider()
            if provider:
                response = await provider.text_chat(
                    prompt=prompt,
                    contexts=[],
                    system_prompt="你是一个记忆检索助手，你的任务是严格按照JSON格式返回检索到的记忆。"
                )
                
                try:
                    # 提取并解析JSON
                    completion_text = response.completion_text.strip()
                    json_match = re.search(r'\{.*\}', completion_text, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                        data = json.loads(json_str)
                        recalled = data.get("recalled_memories", [])
                        # 确保返回的是列表
                        if isinstance(recalled, list):
                            return recalled[:5]
                    self._debug_log("LLM响应中未找到JSON格式", "warning")
                    return [] # 如果没有找到JSON或解析失败
                except json.JSONDecodeError as e:
                    self._debug_log(f"JSON解析失败: {e}, 响应: {completion_text[:200]}...", "error")
                    return [] # JSON解析失败
                except Exception as e:
                    self._debug_log(f"JSON解析异常: {e}", "error")
                    return []
            
            # LLM不可用，回退到简单模式
            return await self._recall_simple(keyword)
            
        except Exception as e:
            logger.error(f"LLM回忆失败: {e}")
            return await self._recall_simple(keyword)

    async def _recall_embedding(self, keyword: str) -> List[str]:
        """基于嵌入向量的相似度回忆"""
        try:
            if not keyword or not self.memory_graph.memories:
                # 随机回忆
                memories = list(self.memory_graph.memories.values())
                if memories:
                    selected = random.sample(memories, min(3, len(memories)))
                    return [m.content for m in selected]
                return []
            
            # 获取关键词的嵌入向量
            keyword_embedding = await self.get_embedding(keyword)
            if not keyword_embedding:
                logger.warning("无法获取关键词嵌入向量，回退到简单模式")
                return await self._recall_simple(keyword)
            
            # 计算与所有记忆的相似度
            memory_similarities = []
            for memory in self.memory_graph.memories.values():
                memory_embedding = await self.get_embedding(memory.content)
                if memory_embedding:
                    similarity = self._cosine_similarity(keyword_embedding, memory_embedding)
                    memory_similarities.append((memory, similarity))
            
            # 按相似度排序
            memory_similarities.sort(key=lambda x: x[1], reverse=True)
            
            # 返回最相似的5条记忆
            return [mem.content for mem, sim in memory_similarities[:5] if sim > 0.3]
            
        except Exception as e:
            logger.error(f"嵌入回忆失败: {e}")
            return await self._recall_simple(keyword)

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        try:
            if len(vec1) != len(vec2):
                return 0.0
            
            dot_product = sum(a * b for a, b in zip(vec1, vec2))
            magnitude1 = sum(a * a for a in vec1) ** 0.5
            magnitude2 = sum(b * b for b in vec2) ** 0.5
            
            if magnitude1 == 0 or magnitude2 == 0:
                return 0.0
            
            return dot_product / (magnitude1 * magnitude2)
        except Exception:
            return 0.0
    
    async def _get_associative_memories(self, core_memories: List[str]) -> List[str]:
        """基于核心记忆获取联想记忆"""
        try:
            if not core_memories or not self.memory_graph.memories:
                return []
            
            # 找到核心记忆对应的概念节点
            core_concepts = set()
            for memory_content in core_memories:
                for memory in self.memory_graph.memories.values():
                    if memory.content == memory_content:
                        core_concepts.add(memory.concept_id)
                        break
            
            if not core_concepts:
                return []
            
            # 收集与核心概念直接相连的相邻概念
            adjacent_concepts = set()
            for concept_id in core_concepts:
                neighbors = self.memory_graph.get_neighbors(concept_id)
                for neighbor_id, strength in neighbors:
                    if neighbor_id not in core_concepts and strength > 0.3:
                        adjacent_concepts.add(neighbor_id)
            
            # 收集相邻概念下的记忆
            associative_memories = []
            for concept_id in adjacent_concepts:
                concept_memories = [
                    m for m in self.memory_graph.memories.values()
                    if m.concept_id == concept_id
                ]
                
                # 按记忆强度和时间排序
                concept_memories.sort(
                    key=lambda m: (m.strength, m.last_accessed),
                    reverse=True
                )
                
                # 每个相邻概念最多添加1条记忆
                if concept_memories:
                    associative_memories.append(concept_memories[0].content)
            
            return associative_memories
            
        except Exception as e:
            logger.error(f"获取联想记忆失败: {e}")
            return []
    
    def _merge_memories_with_associative(self, core_memories: List[str], associative_memories: List[str]) -> List[str]:
        """合并核心记忆和联想记忆"""
        try:
            # 去重并合并
            all_memories = []
            seen = set()
            
            # 核心记忆在前
            for memory in core_memories:
                if memory not in seen:
                    seen.add(memory)
                    all_memories.append(memory)
            
            # 联想记忆在后
            for memory in associative_memories:
                if memory not in seen:
                    seen.add(memory)
                    all_memories.append(memory)
            
            # 限制总数量
            return all_memories[:5]
            
        except Exception as e:
            logger.error(f"合并记忆失败: {e}")
            return core_memories
    
    async def _recall_by_activation(self, keyword: str) -> List[str]:
        """基于激活扩散的回忆算法"""
        try:
            if not self.memory_graph.concepts or not self.memory_graph.memories:
                return []
            
            # 如果没有关键词，随机回忆
            if not keyword:
                memories = list(self.memory_graph.memories.values())
                if memories:
                    selected = random.sample(memories, min(3, len(memories)))
                    return [m.content for m in selected]
                return []
            
            # 找到初始激活的概念节点
            initial_concepts = []
            for concept in self.memory_graph.concepts.values():
                if keyword.lower() in concept.name.lower():
                    initial_concepts.append(concept)
            
            if not initial_concepts:
                # 如果没有直接匹配，使用简单关键词匹配
                return await self._recall_simple(keyword)
            
            # 激活扩散算法
            activation_map = {}  # concept_id -> activation_energy
            visited = set()
            
            # 初始化激活
            for concept in initial_concepts:
                activation_map[concept.id] = 1.0  # 初始能量为1.0
            
            # 扩散参数，以后加配置文件
            decay_factor = 0.7  # 能量衰减因子
            min_threshold = 0.1  # 最小激活阈值
            max_hops = 3  # 最大扩散步数
            
            # 进行扩散
            for hop in range(max_hops):
                new_activations = {}
                
                for concept_id, energy in activation_map.items():
                    if concept_id in visited:
                        continue
                    
                    # 获取该节点的所有连接
                    related_connections = [
                        conn for conn in self.memory_graph.connections
                        if conn.from_concept == concept_id or conn.to_concept == concept_id
                    ]
                    
                    for conn in related_connections:
                        # 确定相邻节点
                        neighbor_id = conn.to_concept if conn.from_concept == concept_id else conn.from_concept
                        
                        if neighbor_id in self.memory_graph.concepts:
                            # 计算传递的能量
                            transferred_energy = energy * conn.strength * decay_factor
                            
                            if transferred_energy > min_threshold:
                                if neighbor_id not in new_activations:
                                    new_activations[neighbor_id] = 0
                                new_activations[neighbor_id] += transferred_energy
                    
                    visited.add(concept_id)
                
                # 合并新的激活
                for concept_id, energy in new_activations.items():
                    if concept_id not in activation_map:
                        activation_map[concept_id] = 0
                    activation_map[concept_id] += energy
            
            # 收集被激活的概念下的记忆
            activated_memories = []
            adjacent_memories = []
            
            # 获取高激活的核心概念
            core_concepts = [
                concept_id for concept_id, energy in activation_map.items()
                if energy > min_threshold
            ]
            
            # 收集核心概念下的记忆
            for concept_id in core_concepts:
                concept_memories = [
                    m for m in self.memory_graph.memories.values()
                    if m.concept_id == concept_id
                ]
                
                # 按记忆强度和时间排序
                concept_memories.sort(
                    key=lambda m: (m.strength, m.last_accessed),
                    reverse=True
                )
                
                # 添加核心记忆
                for memory in concept_memories[:2]:  # 每个概念最多2条记忆
                    activated_memories.append(memory.content)
            
            # 收集相邻概念的记忆（与核心概念直接相连的概念）
            adjacent_concepts = set()
            for concept_id in core_concepts:
                for conn in self.memory_graph.connections:
                    if conn.from_concept == concept_id:
                        adjacent_concepts.add(conn.to_concept)
                    elif conn.to_concept == concept_id:
                        adjacent_concepts.add(conn.from_concept)
            
            # 收集相邻概念下的记忆
            for adjacent_concept_id in adjacent_concepts:
                if adjacent_concept_id in self.memory_graph.concepts:
                    adjacent_concept_memories = [
                        m for m in self.memory_graph.memories.values()
                        if m.concept_id == adjacent_concept_id
                    ]
                    
                    # 按记忆强度和时间排序
                    adjacent_concept_memories.sort(
                        key=lambda m: (m.strength, m.last_accessed),
                        reverse=True
                    )
                    
                    # 添加相邻记忆
                    for memory in adjacent_concept_memories[:1]:  # 每个相邻概念最多1条记忆
                        adjacent_memories.append(memory.content)
            
            # 合并结果：核心记忆在前，相邻记忆在后
            final_memories = activated_memories + adjacent_memories
            
            # 去重并限制数量
            seen = set()
            unique_memories = []
            for memory in final_memories:
                if memory not in seen:
                    seen.add(memory)
                    unique_memories.append(memory)
                    if len(unique_memories) >= 5:  # 最多返回5条
                        break
            
            return unique_memories
            
        except Exception as e:
            logger.error(f"激活扩散回忆失败: {e}")
            return await self._recall_simple(keyword)
    
    async def memory_maintenance_loop(self):
        """记忆维护循环 - 优化版:启动5分钟后执行首次整理,随后按间隔执行"""
        db_dir = os.path.dirname(self.db_path)

        # 1. 启动缓冲:避免抢占启动资源
        self._debug_log("记忆维护任务已就绪,将在 5 分钟后执行首次整理...", "info")
        await asyncio.sleep(300)

        while True:
            try:
                # 2. 醒来直接执行维护逻辑 (先做)
                maintenance_actions = []

                # A. 处理默认数据库
                if self.memory_config["enable_forgetting"]:
                    await self.forget_memories()
                    maintenance_actions.append("遗忘")

                if self.memory_config["enable_consolidation"]:
                    await self.consolidate_memories()
                    maintenance_actions.append("整理")

                await self.save_memory_state()
                maintenance_actions.append("保存")

                # B. 处理群聊隔离数据库
                if self.memory_config.get("enable_group_isolation", True):
                    group_files = []
                    if os.path.exists(db_dir):
                        for filename in os.listdir(db_dir):
                            if filename.startswith("memory_group_") and filename.endswith(".db"):
                                group_id = filename[12:-3]
                                group_files.append(group_id)

                    for group_id in group_files:
                        try:
                            self.memory_graph = MemoryGraph()
                            self.load_memory_state(group_id)

                            if self.memory_config["enable_forgetting"]:
                                await self.forget_memories()

                            if self.memory_config["enable_consolidation"]:
                                await self.consolidate_memories()

                            await self.save_memory_state(group_id)

                        except Exception as group_e:
                            self._debug_log(f"群聊 {group_id} 维护失败: {group_e}", "warning")

                    # 恢复默认状态
                    self.memory_graph = MemoryGraph()
                    self.load_memory_state()

                if maintenance_actions:
                    self._debug_log(f"记忆维护完成: {', '.join(maintenance_actions)}", "info")

                # 3. 维护完成后,进入长睡眠 (后睡)
                interval_hours = self.memory_config.get("consolidation_interval_hours", 24)
                if interval_hours <= 0: interval_hours = 1

                wait_seconds = interval_hours * 3600
                self._debug_log(f"系统将在 {interval_hours} 小时后进行下一次维护", "debug")

                await asyncio.sleep(wait_seconds)

            except Exception as e:
                self._debug_log(f"记忆维护循环异常: {e}", "error")
                await asyncio.sleep(300)


    async def forget_memories(self):
        """遗忘机制"""
        current_time = time.time()
        forget_threshold = self.memory_config["forget_threshold_days"] * 24 * 3600
        
        # 降低连接强度
        connections_to_remove = []
        for connection in self.memory_graph.connections:
            if current_time - connection.last_strengthened > forget_threshold:
                connection.strength *= 0.9
                if connection.strength < 0.1:
                    connections_to_remove.append(connection.id)
        
        # 批量移除连接
        for conn_id in connections_to_remove:
            self.memory_graph.remove_connection(conn_id)
        
        # 移除不活跃的记忆
        memories_to_remove = []
        for memory in list(self.memory_graph.memories.values()):
            if current_time - memory.last_accessed > forget_threshold:
                memory.strength *= 0.8
                if memory.strength < 0.1:
                    memories_to_remove.append(memory.id)
        
        # 批量移除记忆
        for memory_id in memories_to_remove:
            self.memory_graph.remove_memory(memory_id)
        
        # 仅在有实际清理时输出日志
        if len(memories_to_remove) > 0 or len(connections_to_remove) > 0:
            self._debug_log(f"遗忘完成: 清理{len(memories_to_remove)}条记忆, {len(connections_to_remove)}个连接", "info")
        else:
            self._debug_log("遗忘检查完成: 没有需要清理的记忆或连接", "debug")
    
    async def consolidate_memories(self):
        """记忆整理机制 - 智能合并相似记忆"""
        consolidation_count = 0
        
        for concept in list(self.memory_graph.concepts.values()):
            concept_memories = [m for m in self.memory_graph.memories.values()
                              if m.concept_id == concept.id]
            
            if len(concept_memories) > self.memory_config["max_memories_per_topic"]:
                # 按时间排序，优先合并旧记忆
                concept_memories.sort(key=lambda m: m.created_at)
                
                # 使用更智能的合并策略
                merged_memories = []
                used_indices = set()
                
                for i, memory1 in enumerate(concept_memories):
                    if i in used_indices:
                        continue
                        
                    similar_group = [memory1]
                    used_indices.add(i)
                    
                    # 找到所有相似的记忆
                    for j, memory2 in enumerate(concept_memories):
                        if j not in used_indices and self.are_memories_similar(memory1, memory2):
                            similar_group.append(memory2)
                            used_indices.add(j)
                    
                    # 如果找到相似记忆，合并它们
                    if len(similar_group) > 1:
                        merged_content = await self._merge_memories(similar_group)
                        if merged_content:
                            # 保留最新的记忆ID，更新内容
                            newest_memory = max(similar_group, key=lambda m: m.last_accessed)
                            newest_memory.content = merged_content
                            newest_memory.last_accessed = time.time()
                            consolidation_count += len(similar_group) - 1
                            
                            # 收集需要移除的记忆ID
                            memories_to_remove_in_group = []
                            for mem in similar_group:
                                if mem.id != newest_memory.id:
                                    memories_to_remove_in_group.append(mem.id)
                            
                            # 统一移除
                            for mem_id in memories_to_remove_in_group:
                                self.memory_graph.remove_memory(mem_id)
        
        # 仅在有实际合并时输出日志
        if consolidation_count > 0:
            self._debug_log(f"记忆整理完成: 合并{consolidation_count}条相似记忆", "debug")
    
    async def _merge_memories(self, memories: List['Memory']) -> str:
        """智能合并多条相似记忆"""
        if len(memories) == 1:
            return memories[0].content
        
        # 按时间排序
        memories.sort(key=lambda m: m.created_at)
        
        # 提取关键信息
        contents = [m.content for m in memories]
        
        # 使用LLM进行智能合并（如果可用）
        try:
            if self.memory_config["recall_mode"] == "llm":
                provider = await self.get_llm_provider()
                if provider:
                    prompt = f"""请将以下{len(contents)}条相似记忆合并成一条更完整、更准确的记忆：

{chr(10).join(f"{i+1}. {content}" for i, content in enumerate(contents))}

要求：
1. 保留所有重要信息
2. 去除重复内容
3. 保持简洁自然
4. 不超过100字"""
                    
                    response = await provider.text_chat(
                        prompt=prompt,
                        contexts=[],
                        system_prompt="你是一个记忆整理助手，请准确合并相似记忆。"
                    )
                    
                    merged = response.completion_text.strip()
                    if merged and len(merged) > 10:
                        return merged
        except Exception as e:
            logger.warning(f"LLM合并记忆失败: {e}")
        
        # 简单合并策略
        # 提取共同关键词，合并时间信息
        words_list = [content.split() for content in contents]
        common_words = set(words_list[0])
        for words in words_list[1:]:
            common_words &= set(words)
        
        if common_words:
            key_phrase = " ".join(list(common_words)[:5])
            return f"关于{key_phrase}的多次讨论"
        
        # 默认合并
        return contents[-1]  # 返回最新的记忆
    
    def are_memories_similar(self, mem1, mem2) -> bool:
        """判断两条记忆是否相似"""
        # 简单的相似度判断
        words1 = mem1.content.split()
        words2 = mem2.content.split()
        
        # 防止除零错误
        denominator = max(len(words1), len(words2))
        if denominator == 0:
            return False
        
        common_words = set(words1) & set(words2)
        similarity = len(common_words) / denominator
        return similarity > 0.5
    
    async def get_memory_stats(self) -> dict:
        """获取记忆统计信息"""
        return {
            "concepts": len(self.memory_graph.concepts),
            "memories": len(self.memory_graph.memories),
            "connections": len(self.memory_graph.connections),
            "recall_mode": self.memory_config['recall_mode'],
            "llm_provider": self.memory_config['llm_provider'],
            "embedding_provider": self.memory_config['embedding_provider'],
            "enable_forgetting": self.memory_config['enable_forgetting'],
            "enable_consolidation": self.memory_config['enable_consolidation'],
        }

    async def get_llm_provider(self):
        """使用配置文件指定的提供商"""
        try:
            provider_id = self.memory_config.get('llm_provider')
            if not provider_id:
                logger.error("插件配置中未指定 'llm_provider'")
                return None

            # 1. 尝试通过ID精确查找
            provider = self.context.get_provider_by_id(provider_id)
            if provider:
                return provider

            # 2. 如果ID查找失败，尝试通过名称模糊匹配
            all_providers = self.context.get_all_providers()
            for p in all_providers:
                p_name = getattr(getattr(p, 'meta', None), 'name', getattr(p, 'name', None))
                if p_name and p_name.lower() == provider_id.lower():
                    return p
            
            logger.error(f"无法找到配置的LLM提供商: '{provider_id}'")
            available_ids = [f"ID: {getattr(p, 'id', 'N/A')}, Name: {getattr(p, 'name', 'N/A')}" for p in all_providers]
            logger.error(f"可用提供商: {available_ids}")
            return None
            
        except Exception as e:
            logger.error(f"获取LLM提供商失败: {e}", exc_info=True)
            return None

    async def get_embedding_provider(self):
        """使用配置文件指定的提供商"""
        try:
            provider_id = self.memory_config['embedding_provider']
            
            # 获取所有已注册的提供商
            all_providers = self.context.get_all_providers()
            
            # 精确匹配配置的提供商ID
            for provider in all_providers:
                if hasattr(provider, 'id') and provider.id == provider_id:
                    logger.debug(f"成功使用配置指定的嵌入提供商: {provider_id}")
                    return provider
            
            # 如果找不到，尝试通过ID获取
            provider = self.context.get_provider_by_id(provider_id)
            if provider:
                return provider
            
            # 最后尝试通过名称匹配
            for provider in all_providers:
                if hasattr(provider, 'meta') and hasattr(provider.meta, 'name'):
                    if provider.meta.name == provider_id:
                        logger.debug(f"通过名称匹配使用嵌入提供商: {provider_id}")
                        return provider
            
            logger.error(f"无法找到配置的嵌入提供商: {provider_id}")
            return None
            
        except Exception as e:
            logger.error(f"获取嵌入提供商失败: {e}")
            return None

    async def get_embedding(self, text: str) -> List[float]:
        """获取文本的嵌入向量 - 优先使用缓存"""
        # 递归保护：避免嵌入向量获取中的递归调用
        if getattr(self, "_embedding_in_progress", False):
            return []
        self._embedding_in_progress = True
        try:
            # 如果启用了嵌入向量缓存，尝试从缓存获取
            if self.embedding_cache:
                # 生成一个临时ID用于缓存查询
                temp_id = f"temp_{hash(text)}"
                cached_embedding = await self.embedding_cache.get_embedding(temp_id, text)
                if cached_embedding:
                    return cached_embedding
            
            # 缓存未命中或未启用，直接计算
            provider = await self.get_embedding_provider()
            if not provider:
                logger.debug("嵌入提供商不可用")
                return []
            
            # 尝试多种嵌入方法
            methods = ['embedding', 'embeddings', 'get_embedding', 'get_embeddings']
            for method_name in methods:
                if hasattr(provider, method_name):
                    try:
                        method = getattr(provider, method_name)
                        result = await method(text)
                        if result and isinstance(result, list) and len(result) > 0:
                            return result
                    except Exception as e:
                        logger.debug(f"方法 {method_name} 失败: {e}")
                        continue
            
            # 尝试使用LLM提供商的嵌入功能
            if hasattr(provider, 'text_chat'):
                try:
                    # 构建嵌入请求
                    prompt = f"请将以下文本转换为嵌入向量: {text}"
                    response = await provider.text_chat(
                        prompt=prompt,
                        contexts=[],
                        system_prompt="请将文本转换为数值向量表示"
                    )
                    # 这里假设LLM可能返回嵌入向量
                    if response and hasattr(response, 'embedding'):
                        return response.embedding
                except Exception as e:
                    logger.debug(f"LLM嵌入方法失败: {e}")
                
            logger.debug("所有嵌入方法均失败")
            return []
                
        except Exception as e:
            logger.error(f"获取嵌入向量失败: {e}")
            return []
        finally:
            self._embedding_in_progress = False

    async def inject_memories_to_context(self, event: AstrMessageEvent):
        """将相关记忆和印象注入到对话上下文中"""
        try:
            if not self.memory_config.get("enable_enhanced_memory", True):
                return
            
            current_message = event.message_str.strip()
            if not current_message:
                return
            
            # 避免重复注入：检查是否已经有记忆上下文
            if hasattr(event, 'context_extra') and event.context_extra and 'memory_context' in event.context_extra:
                return
            
            # 短消息过滤：避免为过短的消息注入记忆
            if len(current_message) < 3:
                return
            
            # 获取群组ID
            group_id = self._extract_group_id_from_event(event)
            
            # 注入印象上下文（如果启用）
            impression_context = ""
            if self.impression_config.get("enable_impression_injection", True):
                impression_context = await self._inject_impressions_to_context(current_message, group_id)
            
            # 使用增强记忆召回系统获取相关记忆
            from .enhanced_memory_recall import EnhancedMemoryRecall
            
            enhanced_recall = EnhancedMemoryRecall(self)
            results = await enhanced_recall.recall_all_relevant_memories(
                query=current_message,
                max_memories=self.memory_config.get("max_injected_memories", 5),
                group_id=group_id  # 传递群聊ID实现群聊隔离
            )
            
            # 过滤低相关性的记忆
            threshold = self.memory_config.get("memory_injection_threshold", 0.3)
            filtered_results = [r for r in results if hasattr(r, 'relevance_score') and r.relevance_score >= threshold]
            
            # 组合记忆上下文和印象上下文
            combined_context = ""
            if impression_context:
                combined_context += impression_context + "\n\n"
            
            if filtered_results:
                # 使用增强格式化
                memory_context = enhanced_recall.format_memories_for_llm(filtered_results)
                combined_context += memory_context
            
            if combined_context:
                # 注入到AstrBot的上下文中
                if not hasattr(event, 'context_extra'):
                    event.context_extra = {}
                event.context_extra["memory_context"] = combined_context
                
                debug_info = []
                if impression_context:
                    debug_info.append("印象")
                if filtered_results:
                    debug_info.append(f"{len(filtered_results)}条记忆")
                self._debug_log(f"已注入 {'+'.join(debug_info)} 到上下文", "debug")
                
        except Exception as e:
            self._debug_log(f"注入记忆到上下文失败: {e}", "warning")

    async def _inject_impressions_to_context(self, current_message: str, group_id: str) -> str:
        """注入印象信息到对话上下文"""
        try:
            # 从消息中提取人名
            mentioned_names = self._extract_mentioned_names(current_message)
            if not mentioned_names:
                return ""
            
            # 获取发送者名称
            sender_name = self._extract_sender_name_from_message(current_message)
            
            # 合并所有相关人名（包括发送者和提及的人）
            all_names = set()
            if sender_name:
                all_names.add(sender_name)
            all_names.update(mentioned_names)
            
            # 获取这些人的印象信息
            impression_lines = []
            for name in all_names:
                impression_summary = self.get_person_impression_summary(group_id, name)
                if impression_summary and impression_summary.get("summary"):
                    score = impression_summary.get("score", 0.5)
                    score_desc = self._score_to_description(score)
                    impression_lines.append(f"- {name}: {impression_summary['summary']} (好感度: {score_desc})")
            
            if impression_lines:
                return "【人物印象】\n" + "\n".join(impression_lines)
            
            return ""
            
        except Exception as e:
            self._debug_log(f"注入印象上下文失败: {e}", "warning")
            return ""

    def _extract_mentioned_names(self, message: str) -> List[str]:
        """从消息中提取提到的人名"""
        try:
            # 简单的人名提取，匹配常见的中文名模式
            # 2-4个中文字符，且不是常见词汇
            common_words = {"你好", "谢谢", "再见", "好的", "是的", "不是", "可以", "不行", "知道", "不知道", "明白", "不明白"}
            names = set()
            
            # 匹配2-4个中文字符
            chinese_names = re.findall(r'[\u4e00-\u9fff]{2,4}', message)
            
            for name in chinese_names:
                if name not in common_words:
                    names.add(name)
            
            return list(names)
            
        except Exception as e:
            self._debug_log(f"提取人名失败: {e}", "debug")
            return []

    def _extract_sender_name_from_message(self, message: str) -> Optional[str]:
        """从消息中提取发送者名称"""
        try:
            # 这里可以根据实际情况实现更复杂的逻辑
            # 目前简单返回None，让调用者处理
            return None
            
        except Exception as e:
            self._debug_log(f"提取发送者名称失败: {e}", "debug")
            return None

    def _score_to_description(self, score: float) -> str:
        """将好感度分数转换为描述性文字"""
        try:
            if score >= 0.8:
                return "很高"
            elif score >= 0.6:
                return "较高"
            elif score >= 0.4:
                return "一般"
            elif score >= 0.2:
                return "较低"
            else:
                return "很低"
                
        except Exception as e:
            self._debug_log(f"分数描述转换失败: {e}", "debug")
            return "一般"

    def _extract_person_name_from_theme(self, theme: str) -> Optional[str]:
        """从主题中提取人物姓名
        
        Args:
            theme: 主题字符串，可能包含人物姓名
            
        Returns:
            str: 提取的人物姓名，无法提取则返回None
        """
        try:
            # 清理主题字符串
            theme = theme.strip()
            if not theme:
                return None
            
            # 分割主题（可能包含多个关键词）
            parts = theme.split(',')
            
            # 查找包含人名的部分
            for part in parts:
                part = part.strip()
                
                # 跳过明显的非人名关键词
                if part in ["印象", "评价", "看法", "感觉", "印象", "人际"]:
                    continue
                
                # 检查是否是有效的人名（2-4个中文字符）
                if len(part) >= 2 and len(part) <= 4 and re.match(r'^[\u4e00-\u9fff]+$', part):
                    return part
            
            return None
            
        except Exception as e:
            self._debug_log(f"从主题提取人名失败: {e}", "debug")
            return None

    async def query_memory(self, query: str, event: AstrMessageEvent = None) -> List[str]:
        """记忆查询接口"""
        try:
            if not query:
                return []
                
            # 使用统一的回忆接口
            return await self.recall_memories(query, event)
            
        except Exception as e:
            logger.error(f"记忆查询失败: {e}")
            return []

    async def recall_memories(self, keyword: str, event: AstrMessageEvent = None) -> List[str]:
        """回忆相关记忆，回忆接口"""
        try:
            if not self.memory_graph.memories:
                return []
                
            # 根据配置的回忆模式选择合适的方法
            recall_mode = self.memory_config["recall_mode"]
            
            if recall_mode == "llm":
                return await self._recall_llm(keyword, event)
            elif recall_mode == "embedding":
                return await self._recall_embedding(keyword)
            elif recall_mode == "activation":
                return await self._recall_by_activation(keyword)
            else:
                return await self._recall_simple(keyword)
                
        except Exception as e:
            logger.error(f"回忆记忆失败: {e}")
            return await self._recall_simple(keyword)

    async def recall_relevant_memories(self, message: str) -> List[str]:
        """基于消息内容智能召回相关记忆"""
        try:
            if not self.memory_graph.memories:
                return []
            
            # 使用增强记忆召回系统
            from .enhanced_memory_recall import EnhancedMemoryRecall
            
            enhanced_recall = EnhancedMemoryRecall(self)
            results = await enhanced_recall.recall_all_relevant_memories(
                query=message,
                max_memories=self.memory_config.get("max_injected_memories", 5)
            )
            
            # 返回记忆内容列表
            return [result.memory for result in results]
            
        except Exception as e:
            logger.error(f"增强记忆召回失败: {e}")
            return []

    def format_memories_for_context(self, memories: List[str]) -> str:
        """将记忆格式化为适合LLM理解的增强上下文"""
        try:
            if not memories:
                return ""
            
            # 使用增强格式化
            from .enhanced_memory_recall import EnhancedMemoryRecall, MemoryRecallResult
            
            # 创建增强结果用于格式化
            enhanced_results = []
            for memory in memories:
                enhanced_results.append(MemoryRecallResult(
                    memory=memory,
                    relevance_score=0.8,
                    memory_type='context_injection',
                    concept_id='',
                    metadata={'source': 'auto_injection'}
                ))
            
            enhanced_recall = EnhancedMemoryRecall(self)
            return enhanced_recall.format_memories_for_llm(enhanced_results)
            
        except Exception as e:
            logger.error(f"上下文格式化失败: {e}")
            return ""
    
    def ensure_person_impression(self, group_id: str, person_name: str) -> str:
        """确保指定群组的人物印象概念存在，返回概念ID
        
        Args:
            group_id: 群组ID，用于跨群隔离
            person_name: 人物名称
            
        Returns:
            str: 概念ID
        """
        try:
            # 构建印象概念名称，格式：Imprint:GROUPID:NAME
            concept_name = f"Imprint:{group_id}:{person_name}"
            
            # 检查是否已存在
            for concept in self.memory_graph.concepts.values():
                if concept.name == concept_name:
                    return concept.id
            
            # 创建新的印象概念
            concept_id = self.memory_graph.add_concept(concept_name)
            self._debug_log(f"创建新印象概念: {concept_name}", "debug")
            
            return concept_id
            
        except Exception as e:
            self._debug_log(f"确保印象概念失败: {e}", "error")
            return ""
    
    def record_person_impression(self, group_id: str, person_name: str, summary: str,
                               score: Optional[float] = None, details: str = "") -> str:
        """记录或更新人物印象
        
        Args:
            group_id: 群组ID
            person_name: 人物名称
            summary: 印象摘要
            score: 好感度分数 (0-1)，默认使用配置的默认值
            details: 详细信息
            
        Returns:
            str: 记忆ID
        """
        try:
            # 确保印象概念存在
            concept_id = self.ensure_person_impression(group_id, person_name)
            if not concept_id:
                return ""
            
            # 使用默认分数或指定分数
            if score is None:
                score = float(self.impression_config["default_score"])
            
            # 确保score是float类型
            score = float(score)
            
            # 限制分数范围
            score = max(float(self.impression_config["min_score"]),
                       min(float(self.impression_config["max_score"]), score))
            
            # 创建印象记忆 - 确保设置正确的group_id
            memory_id = self.memory_graph.add_memory(
                content=summary,
                concept_id=concept_id,
                details=details,
                participants=person_name,
                emotion="印象",
                tags="人际",
                strength=score,
                group_id=group_id
            )
            
            self._debug_log(f"记录印象: {person_name} (分数: {score}, 群组: {group_id})", "debug")
            
            return memory_id
            
        except Exception as e:
            self._debug_log(f"记录印象失败: {e}", "error")
            return ""
    
    def get_impression_score(self, group_id: str, person_name: str) -> float:
        """获取人物的好感度分数
        
        Args:
            group_id: 群组ID
            person_name: 人物名称
            
        Returns:
            float: 好感度分数，未找到返回默认值
        """
        try:
            concept_name = f"Imprint:{group_id}:{person_name}"
            
            # 查找对应的印象概念
            concept_id = None
            for concept in self.memory_graph.concepts.values():
                if concept.name == concept_name:
                    concept_id = concept.id
                    break
            
            if not concept_id:
                return self.impression_config["default_score"]
            
            # 获取该概念下最新的记忆（即最新印象）- 使用群聊隔离过滤
            all_concept_memories = [
                m for m in self.memory_graph.memories.values()
                if m.concept_id == concept_id
            ]
            
            # 应用群聊隔离过滤
            concept_memories = self.filter_memories_by_group(all_concept_memories, group_id)
            
            if not concept_memories:
                return self.impression_config["default_score"]
            
            # 按时间排序，获取最新的印象分数
            latest_memory = max(concept_memories, key=lambda m: m.last_accessed)
            return latest_memory.strength
            
        except Exception as e:
            self._debug_log(f"获取印象分数失败: {e}", "error")
            return self.impression_config["default_score"]
    
    def adjust_impression_score(self, group_id: str, person_name: str, delta: float) -> float:
        """调整人物的好感度分数
        
        Args:
            group_id: 群组ID
            person_name: 人物名称
            delta: 调整增量（可正可负）
            
        Returns:
            float: 调整后的新分数
        """
        try:
            # 获取当前分数
            current_score = self.get_impression_score(group_id, person_name)
            
            # 计算新分数
            new_score = current_score + delta
            new_score = max(self.impression_config["min_score"],
                           min(self.impression_config["max_score"], new_score))
            
            # 获取印象概念
            concept_name = f"Imprint:{group_id}:{person_name}"
            concept_id = None
            for concept in self.memory_graph.concepts.values():
                if concept.name == concept_name:
                    concept_id = concept.id
                    break
            
            if concept_id:
                # 查找现有的印象记忆 - 使用群聊隔离过滤
                all_concept_memories = [
                    m for m in self.memory_graph.memories.values()
                    if m.concept_id == concept_id
                ]
                
                # 应用群聊隔离过滤
                concept_memories = self.filter_memories_by_group(all_concept_memories, group_id)
                
                if concept_memories:
                    # 更新最新一条印象记忆的强度
                    latest_memory = max(concept_memories, key=lambda m: m.last_accessed)
                    latest_memory.strength = new_score
                    latest_memory.last_accessed = time.time()
                    self._debug_log(f"更新现有印象记忆强度: {person_name} -> {new_score:.2f}", "debug")
                else:
                    # 如果没有现有记忆，创建新的
                    summary = f"对{person_name}的印象更新，当前好感度：{new_score:.2f}"
                    self.record_person_impression(group_id, person_name, summary, new_score)
            else:
                # 如果概念不存在，创建新的印象
                summary = f"对{person_name}的印象更新，当前好感度：{new_score:.2f}"
                self.record_person_impression(group_id, person_name, summary, new_score)
            
            self._debug_log(f"调整印象分数: {person_name} {current_score:.2f} -> {new_score:.2f}", "debug")
            
            return new_score
            
        except Exception as e:
            self._debug_log(f"调整印象分数失败: {e}", "error")
            return self.get_impression_score(group_id, person_name)
    
    def get_person_impression_summary(self, group_id: str, person_name: str) -> Dict[str, Any]:
        """获取人物印象摘要信息
        
        Args:
            group_id: 群组ID
            person_name: 人物名称
            
        Returns:
            dict: 包含印象摘要的字典
        """
        try:
            concept_name = f"Imprint:{group_id}:{person_name}"
            
            # 查找对应的印象概念
            concept_id = None
            concept = None
            for c in self.memory_graph.concepts.values():
                if c.name == concept_name:
                    concept_id = c.id
                    concept = c
                    break
            
            if not concept_id or not concept:
                return {
                    "name": person_name,
                    "score": self.impression_config["default_score"],
                    "summary": f"尚未建立对{person_name}的印象",
                    "memory_count": 0,
                    "last_updated": "无"
                }
            
            # 获取该概念下的所有印象记忆 - 使用群聊隔离过滤
            all_impression_memories = [
                m for m in self.memory_graph.memories.values()
                if m.concept_id == concept_id
            ]
            
            # 应用群聊隔离过滤
            impression_memories = self.filter_memories_by_group(all_impression_memories, group_id)
            
            if not impression_memories:
                return {
                    "name": person_name,
                    "score": self.impression_config["default_score"],
                    "summary": f"对{person_name}的印象记录为空",
                    "memory_count": 0,
                    "last_updated": "无"
                }
            
            # 获取最新印象
            latest_memory = max(impression_memories, key=lambda m: m.last_accessed)
            current_score = latest_memory.strength
            
            # 获取印象摘要
            summary = latest_memory.content
            
            # 格式化时间 - 确保last_accessed是datetime对象
            try:
                if isinstance(latest_memory.last_accessed, (int, float)):
                    # 如果是时间戳，转换为datetime
                    dt = datetime.fromtimestamp(latest_memory.last_accessed)
                    last_updated = dt.strftime("%Y-%m-%d %H:%M:%S")
                elif hasattr(latest_memory.last_accessed, 'strftime'):
                    # 如果已经有strftime方法，直接使用
                    last_updated = latest_memory.last_accessed.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    # 其他情况，使用当前时间
                    last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            except Exception as time_e:
                self._debug_log(f"时间格式化失败: {time_e}", "warning")
                last_updated = "时间格式化失败"
            
            return {
                "name": person_name,
                "score": current_score,
                "summary": summary,
                "memory_count": len(impression_memories),
                "last_updated": last_updated
            }
            
        except Exception as e:
            self._debug_log(f"获取印象摘要失败: {e}", "error")
            return {
                "name": person_name,
                "score": self.impression_config["default_score"],
                "summary": "获取印象信息失败",
                "memory_count": 0,
                "last_updated": "无"
            }
    
    def get_person_impression_memories(self, group_id: str, person_name: str, limit: int = 5) -> List[Dict[str, Any]]:
        """获取人物印象相关的记忆列表
        
        Args:
            group_id: 群组ID
            person_name: 人物名称
            limit: 返回的记忆数量限制
            
        Returns:
            List[dict]: 记忆列表
        """
        try:
            concept_name = f"Imprint:{group_id}:{person_name}"
            
            # 查找对应的印象概念
            concept_id = None
            for c in self.memory_graph.concepts.values():
                if c.name == concept_name:
                    concept_id = c.id
                    break
            
            if not concept_id:
                return []
            
            # 获取该概念下的所有印象记忆 - 使用群聊隔离过滤
            all_impression_memories = [
                m for m in self.memory_graph.memories.values()
                if m.concept_id == concept_id
            ]
            
            # 应用群聊隔离过滤
            impression_memories = self.filter_memories_by_group(all_impression_memories, group_id)
            
            # 按时间倒序排序
            impression_memories.sort(key=lambda m: m.last_accessed, reverse=True)
            
            # 限制数量
            impression_memories = impression_memories[:limit]
            
            # 转换为字典格式
            memories_list = []
            for memory in impression_memories:
                memories_list.append({
                    "id": memory.id,
                    "content": memory.content,
                    "details": memory.details or "",
                    "score": memory.strength,
                    "created": self._safe_format_datetime(memory.created_at),
                    "last_accessed": self._safe_format_datetime(memory.last_accessed)
                })
            
            return memories_list
            
        except Exception as e:
            self._debug_log(f"获取印象记忆失败: {e}", "error")
            return []
    
    def _safe_format_datetime(self, dt_obj) -> str:
        """安全地格式化datetime对象或时间戳"""
        try:
            if isinstance(dt_obj, (int, float)):
                dt = datetime.fromtimestamp(dt_obj)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            elif hasattr(dt_obj, 'strftime'):
                return dt_obj.strftime("%Y-%m-%d %H:%M:%S")
            else:
                return str(dt_obj)
        except Exception as e:
            self._debug_log(f"安全格式化时间失败: {e}", "warning")
            return "未知时间"


class BatchMemoryExtractor:
    """记忆提取器，通过LLM调用获取多个记忆点和主题"""
    
    def __init__(self, memory_system):
        self.memory_system = memory_system
    
    async def extract_impressions_from_conversation(self, conversation_history: List[Dict[str, Any]], group_id: str) -> List[Dict[str, Any]]:
        """
        从对话中提取人物印象
        
        Args:
            conversation_history: 对话历史
            group_id: 群组ID
            
        Returns:
            人物印象列表
        """
        if not conversation_history:
            return []
        
        formatted_history = self._format_conversation_history(conversation_history)
        
        prompt = f"""请从以下对话中提取人物印象信息。

对话历史：
{formatted_history}

任务要求：
1. 识别对话中涉及的所有人物
2. 提取每个人物的印象描述
3. 为每个印象提供：
   - person_name: 人物姓名
   - summary: 印象摘要
   - score: 好感度分数（0-1）
   - details: 详细描述
   - confidence: 置信度（0-1）

返回格式：
{{
  "impressions": [
    {{
      "person_name": "张三",
      "summary": "友善且乐于助人",
      "score": 0.8,
      "details": "主动提供帮助，态度友好",
      "confidence": 0.9
    }}
  ]
}}

只返回JSON格式
"""

        try:
            provider = await self.memory_system.get_llm_provider()
            if not provider:
                return []
            
            response = await provider.text_chat(
                prompt=prompt,
                contexts=[],
                system_prompt="你是一个人物印象提取助手"
            )
            
            data = json.loads(response.completion_text)
            impressions = data.get("impressions", [])
            
            # 过滤有效印象
            valid_impressions = []
            for impression in impressions:
                if impression.get("person_name") and impression.get("summary"):
                    valid_impressions.append({
                        "person_name": str(impression["person_name"]),
                        "summary": str(impression["summary"]),
                        "score": float(impression.get("score", 0.5)),
                        "details": str(impression.get("details", "")),
                        "confidence": float(impression.get("confidence", 0.7))
                    })
            
            return valid_impressions
            
        except Exception as e:
            logger.error(f"提取人物印象失败: {e}")
            return []
    
    async def extract_memories_and_themes(self, conversation_history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not conversation_history:
            return []
        formatted_history = self._format_conversation_history(conversation_history)
        prompt = f"""请从以下对话中提取丰富、详细、准确的记忆信息。对话包含完整的发送者信息和时间戳。
对话历史:
{formatted_history}
任务要求:
1. 识别所有有意义的记忆点,包括:
   - 重要事件(高置信度:0.7-1.0)
   - 日常小事(中置信度:0.4-0.7)
   - 有趣细节(低置信度:0.1-0.4)
   - 人物印象(对他人评价、看法或互动)
2. 为每个记忆生成完整信息:
   - 主题(theme):核心关键词,用逗号分隔
   - 内容(content):简洁的核心记忆
   - 细节(details):具体细节和背景,丰富、详细、准确的记忆信息
   - 参与者(participants):涉及的人物,特别注意:如果发言者是[Bot],则使用"我"或Bot的身份作为参与者;如果是用户,则使用用户名称
   - 地点(location):相关场景
   - 情感(emotion):情感色彩
   - 标签(tags):分类标签
   - 置信度(confidence):0-1之间的数值
   - 记忆类型(memory_type):"normal"(普通记忆)或"impression"(人物印象)
3. 可以生成多个记忆,包括小事
4. 返回JSON格式
特别注意:
- 请仔细区分[Bot]和用户的发言
- 当[Bot]发言时,在参与者字段使用第一人称"我"而不是"其他用户"
- 确保LLM在后续上下文引用时能准确区分Bot的自我表述与用户的外部输入
- 对于人物印象记忆:memory_type设为"impression",并在theme中包含人物姓名
- 对于普通记忆:memory_type设为"normal"
- 当对话中涉及对他人(非Bot)的评价、看法或互动时,创建印象记忆
返回格式:
{{
  "memories": [
    {{
      "theme": "工作,项目",
      "content": "今天完成了项目演示",
      "details": "丰富、详细、准确的记忆信息",
      "participants": "我,客户,项目经理",
      "location": "会议室",
      "emotion": "兴奋,满意",
      "tags": "重要,成功",
      "confidence": 0.9,
      "memory_type": "normal"
    }}
  ]
}}
要求:
- 捕捉所有有意义的对话内容
- 小事也可以记录,降低置信度即可
- 内容要具体、生动
- 可以生成5-8个记忆
- 特别注意识别人物印象,当涉及对他人评价时创建印象记忆
- 印象记忆的theme应包含人物姓名和"印象"关键词
- 只返回JSON"""
        try:
            provider = await self.memory_system.get_llm_provider()
            if not provider:
                return await self._fallback_extraction(conversation_history)
            try:
                # --- 核心修改:使用配置中的 System Prompt (Rosa适配关键) ---
                sys_prompt = self.memory_system.memory_config.get("llm_system_prompt", "你是一个专业的记忆提取助手,请准确提取对话中的关键信息。")
                response = await provider.text_chat(prompt=prompt, contexts=[], system_prompt=sys_prompt)
                return self._parse_batch_response(response.completion_text)
            except Exception as e:
                logger.warning(f"LLM调用失败: {e}")
                return await self._fallback_extraction(conversation_history)
        except Exception:
            return await self._fallback_extraction(conversation_history)


    def _format_conversation_history(self, history: List[Dict[str, Any]]) -> str:
        """格式化对话历史，包含完整信息，并区分Bot和用户发言"""
        formatted_lines = []
        for msg in history:
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', '')
            role = msg.get('role', 'user')
            sender = msg.get('sender_name', '用户')
            
            # 格式化时间戳
            if isinstance(timestamp, (int, float)):
                dt = datetime.fromtimestamp(timestamp)
                time_str = dt.strftime('%m-%d %H:%M')
            else:
                time_str = str(timestamp)
            
            # 根据角色区分Bot和用户消息
            if role == "assistant":
                # Bot消息，标识为"[Bot]"
                formatted_lines.append(f"[{time_str}] [Bot]: {content}") #会改
            else:
                # 用户消息，保持原格式
                formatted_lines.append(f"[{time_str}] {sender}: {content}")
        
        return "\n".join(formatted_lines)
    
    def _parse_batch_response(self, response_text: str) -> List[Dict[str, Any]]:
        """解析批量提取的LLM响应"""
        try:
            # 清理响应文本，处理中文引号和格式问题
            cleaned_text = response_text
            for old, new in [('“', '"'), ('”', '"'), ('‘', "'"), ('’', "'"), ('，', ','), ('：', ':')]:
                cleaned_text = cleaned_text.replace(old, new)
            
            # 尝试多种JSON提取方式
            json_patterns = [
                r'\{[^{}]*"memories"[^{}]*\}',  # 简单JSON对象
                r'\{.*"memories"\s*:\s*\[.*\].*\}',  # 包含memories数组的完整对象
                r'\{.*\}',  # 最宽泛的匹配
            ]
            
            json_str = None
            for pattern in json_patterns:
                matches = re.findall(pattern, cleaned_text, re.DOTALL)
                if matches:
                    json_str = matches[-1]  # 取最后一个匹配
                    break
            
            if not json_str:
                return []
            
            # 修复常见的JSON格式问题
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            json_str = re.sub(r'([{,]\s*)(\w+):', r'\1"\2":', json_str)  # 修复未加引号的键
            
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # 更激进的修复，记录错误但不输出过多日志
                json_str = re.sub(r'([{,]\s*)"([^"]*)"\s*:\s*([^",}\]]+)([,\}])', r'\1"\2": "\3"\4', json_str)
                data = json.loads(json_str)
            
            memories = data.get("memories", [])
            if not isinstance(memories, list):
                return []
            
            # 过滤和验证记忆
            filtered_memories = []
            for i, mem in enumerate(memories):
                try:
                    if not isinstance(mem, dict):
                        continue
                    
                    # 安全地获取每个字段，确保类型正确
                    confidence = 0.7
                    try:
                        confidence_val = mem.get("confidence", 0.7)
                        if isinstance(confidence_val, (int, float)):
                            confidence = float(confidence_val)
                        elif isinstance(confidence_val, str):
                            confidence = float(confidence_val)
                    except (ValueError, TypeError):
                        confidence = 0.7
                    
                    theme = ""
                    try:
                        theme_val = mem.get("theme", "")
                        theme = str(theme_val).strip()
                    except (ValueError, TypeError):
                        theme = ""
                    
                    content = ""
                    try:
                        content_val = mem.get("content", "")
                        content = str(content_val).strip()
                    except (ValueError, TypeError):
                        content = ""
                    
                    details = ""
                    try:
                        details_val = mem.get("details", "")
                        details = str(details_val).strip()
                    except (ValueError, TypeError):
                        details = ""
                    
                    participants = ""
                    try:
                        participants_val = mem.get("participants", "")
                        participants = str(participants_val).strip()
                    except (ValueError, TypeError):
                        participants = ""
                    
                    location = ""
                    try:
                        location_val = mem.get("location", "")
                        location = str(location_val).strip()
                    except (ValueError, TypeError):
                        location = ""
                    
                    emotion = ""
                    try:
                        emotion_val = mem.get("emotion", "")
                        emotion = str(emotion_val).strip()
                    except (ValueError, TypeError):
                        emotion = ""
                    
                    tags = ""
                    try:
                        tags_val = mem.get("tags", "")
                        tags = str(tags_val).strip()
                    except (ValueError, TypeError):
                        tags = ""
                    
                    memory_type = "normal"
                    try:
                        memory_type_val = mem.get("memory_type", "normal")
                        memory_type = str(memory_type_val).strip().lower()
                    except (ValueError, TypeError):
                        memory_type = "normal"
                    
                    # 清理主题中的特殊字符
                    theme = re.sub(r'[^\w\u4e00-\u9fff,，]', '', theme)
                    
                    if theme and content and confidence > 0.3:
                        filtered_memories.append({
                            "theme": theme,
                            "content": content,
                            "details": details,
                            "participants": participants,
                            "location": location,
                            "emotion": emotion,
                            "tags": tags,
                            "confidence": max(0.0, min(1.0, confidence)),
                            "memory_type": memory_type if memory_type in ["normal", "impression"] else "normal"
                        })
                        
                except (ValueError, TypeError, AttributeError):
                    continue
            
            return filtered_memories
            
        except Exception:
            return []
    
    async def _fallback_extraction(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """回退到简单提取模式"""
        if not history:
            return []
        
        # 简单关键词提取
        text = " ".join([msg.get('content', '') for msg in history])
        themes = self._extract_simple_themes(text)
        
        memories = []
        for theme in themes[:3]:
            memory_content = f"我们聊过关于{theme}的事情"
            memories.append({
                "theme": theme,
                "memory_content": memory_content,
                "confidence": 0.5
            })
        
        return memories
    
    def _extract_simple_themes(self, text: str) -> List[str]:
        """简单主题提取"""
        # 提取中文关键词
        words = re.findall(r'\b[\u4e00-\u9fff]{2,4}\b', text)
        word_freq = {}
        
        for word in words:
            if len(word) >= 2 and word not in ["你好", "谢谢", "再见"]:
                word_freq[word] = word_freq.get(word, 0) + 1
        
        # 返回频率最高的关键词
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [word for word, freq in sorted_words[:5]]


class MemoryGraph:
    """记忆图数据结构"""
    
    def __init__(self):
        self.concepts: Dict[str, Concept] = {}
        self.memories: Dict[str, Memory] = {}
        self.connections: List[Connection] = []
        self.adjacency_list: Dict[str, List[Tuple[str, float]]] = {}  # 邻接表优化
        
    def add_concept(self, name: str, concept_id: str = None, created_at: float = None,
                   last_accessed: float = None, access_count: int = 0) -> str:
        """添加概念节点"""
        if concept_id is None:
            concept_id = f"concept_{int(time.time() * 1000)}"
        
        if concept_id not in self.concepts:
            concept = Concept(
                id=concept_id,
                name=name,
                created_at=created_at,
                last_accessed=last_accessed,
                access_count=access_count
            )
            self.concepts[concept_id] = concept
            if concept_id not in self.adjacency_list:
                self.adjacency_list[concept_id] = []
        
        return concept_id
    
    def add_memory(self, content: str, concept_id: str, memory_id: str = None,
                   details: str = "", participants: str = "", location: str = "",
                   emotion: str = "", tags: str = "", created_at: float = None,
                   last_accessed: float = None, access_count: int = 0,
                   strength: float = 1.0, group_id: str = "") -> str:
        """添加记忆"""
        if memory_id is None:
            memory_id = f"memory_{int(time.time() * 1000)}"
        
        memory = Memory(
            id=memory_id,
            concept_id=concept_id,
            content=content,
            details=details,
            participants=participants,
            location=location,
            emotion=emotion,
            tags=tags,
            created_at=created_at,
            last_accessed=last_accessed,
            access_count=access_count,
            strength=strength,
            group_id=group_id
        )
        self.memories[memory_id] = memory
        
        # 如果启用了嵌入向量缓存，调度预计算任务
        if hasattr(self, 'embedding_cache') and self.embedding_cache:
            asyncio.create_task(self.embedding_cache.schedule_precompute_task([memory_id], priority=3))
        
        return memory_id
    def add_connection(self, from_concept: str, to_concept: str,
                      strength: float = 1.0, connection_id: str = None,
                      last_strengthened: float = None) -> str:
        """添加连接"""
        if connection_id is None:
            connection_id = f"conn_{from_concept}_{to_concept}"
        
        # 检查是否已存在
        for conn in self.connections:
            if (conn.from_concept == from_concept and conn.to_concept == to_concept) or \
               (conn.from_concept == to_concept and conn.to_concept == from_concept):
                conn.strength += 0.1
                conn.last_strengthened = time.time()
                return conn.id
        
        connection = Connection(
            id=connection_id,
            from_concept=from_concept,
            to_concept=to_concept,
            strength=strength,
            last_strengthened=last_strengthened or time.time()
        )
        self.connections.append(connection)
        
        # 更新邻接表
        if from_concept not in self.adjacency_list:
            self.adjacency_list[from_concept] = []
        if to_concept not in self.adjacency_list:
            self.adjacency_list[to_concept] = []
        
        # 添加双向连接
        self.adjacency_list[from_concept].append((to_concept, strength))
        self.adjacency_list[to_concept].append((from_concept, strength))
        
        return connection_id
    
    def remove_connection(self, connection_id: str):
        """移除连接"""
        # 找到要移除的连接
        conn_to_remove = None
        for conn in self.connections:
            if conn.id == connection_id:
                conn_to_remove = conn
                break
        
        if conn_to_remove:
            # 从连接列表中移除
            self.connections = [c for c in self.connections if c.id != connection_id]
            
            # 更新邻接表
            if conn_to_remove.from_concept in self.adjacency_list:
                self.adjacency_list[conn_to_remove.from_concept] = [
                    (neighbor, strength) for neighbor, strength in self.adjacency_list[conn_to_remove.from_concept]
                    if neighbor != conn_to_remove.to_concept
                ]
            
            if conn_to_remove.to_concept in self.adjacency_list:
                self.adjacency_list[conn_to_remove.to_concept] = [
                    (neighbor, strength) for neighbor, strength in self.adjacency_list[conn_to_remove.to_concept]
                    if neighbor != conn_to_remove.from_concept
                ]
    
    def remove_memory(self, memory_id: str):
        """移除记忆"""
        if memory_id in self.memories:
            del self.memories[memory_id]
    
    def get_neighbors(self, concept_id: str) -> List[Tuple[str, float]]:
        """获取概念节点的邻居及其连接强度"""
        return self.adjacency_list.get(concept_id, [])


@dataclass
class Concept:
    """概念节点"""
    id: str
    name: str
    created_at: float = None
    last_accessed: float = None
    access_count: int = 0
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.last_accessed is None:
            self.last_accessed = time.time()


@dataclass
class Memory:
    """记忆条目"""
    id: str
    concept_id: str
    content: str
    details: str = ""  # 详细描述
    participants: str = ""  # 参与者
    location: str = ""  # 地点
    emotion: str = ""  # 情感
    tags: str = ""  # 标签
    created_at: float = None
    last_accessed: float = None
    access_count: int = 0
    strength: float = 1.0
    group_id: str = ""  # 群组ID，用于群聊隔离
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.last_accessed is None:
            self.last_accessed = time.time()


@dataclass
class Connection:
    """概念之间的连接"""
    id: str
    from_concept: str
    to_concept: str
    strength: float = 1.0
    last_strengthened: float = None
    
    def __post_init__(self):
        if self.last_strengthened is None:
            self.last_strengthened = time.time()
