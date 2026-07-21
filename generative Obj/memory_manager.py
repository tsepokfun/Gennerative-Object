"""
============================================================
  動態多智能體元沙盤推演系統 - 向量記憶管理器 (ChromaDB)
  Dynamic Multi-Agent Meta-Simulation Platform - Vector Memory
============================================================
  對比舊版 ObjInfo.py：
  - 舊版：Memory 只是純文字字串，每次用 LLM 覆蓋更新 (ObjInfo.upd)
  - 舊版：無檢索能力，智能體只能看到「上一次更新後的記憶」
  - 舊版：無向量化，無法做語義相似度查詢
  
  新版：
  - 每個智能體的每日經歷以向量形式存入 ChromaDB
  - 支援語義檢索 (Semantic Search) Top-K 相關歷史記憶
  - 每個模擬 (simulation) 擁有獨立 Collection，互不干擾
  - 記憶附帶結構化 metadata (day, action_type, emotion) 方便過濾
============================================================
"""

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions
from typing import List, Dict, Optional, Any
from datetime import datetime
import json
import os

from models import AgentAction, EnvironmentState


# ============================================================
#  記憶條目結構 (儲存於 ChromaDB metadata)
# ============================================================

class EpisodicMemory:
    """
    單條情景記憶的內部表示
    
    此類別封裝了一條記憶在寫入 ChromaDB 前的結構化表示。
    documents: 自然語言描述 (會被向量化)
    metadatas: 結構化過濾欄位
    ids: 唯一識別碼
    """
    
    @staticmethod
    def build(
        agent_id: str,
        day: int,
        context: str,
        action: AgentAction,
        emotion: str = "neutral"
    ) -> tuple[str, Dict[str, Any], str]:
        """
        構建一條記憶條目
        
        Args:
            agent_id: 智能體 ID
            day: 模擬日
            context: 當前情境描述（當天環境狀態摘要）
            action: 智能體執行的行動 (AgentAction)
            emotion: 當前情緒狀態
        
        Returns:
            (document, metadata, id) 三元組，直接寫入 ChromaDB
        """
        memory_id = f"{agent_id}_day{day}_{datetime.now().timestamp()}"
        
        # 自然語言記憶文本（會被向量化） — 對比舊版 ObjInfo.Memory 的純文字
        document = (
            f"第 {day} 天，{context}。"
            f"{action.action_description}。"
            f"情緒狀態：{emotion}。"
        )
        
        # 結構化 metadata — 舊版完全沒有這層資訊
        metadata = {
            "agent_id": agent_id,
            "day": day,
            "action_type": action.action_type,
            "emotion": emotion,
            "target_agent_id": action.target_agent_id or "",
            "duration_minutes": action.duration_minutes,
            "environment_effects": json.dumps(action.environment_effects),
            "timestamp": datetime.now().isoformat(),
        }
        
        return document, metadata, memory_id


# ============================================================
#  ChromaDB 記憶管理器
# ============================================================

class MemoryManager:
    """
    向量記憶管理器 — 取代舊版 ObjInfo.py 的 Memory list
    
    使用 ChromaDB 作為後端，支援：
    1. 語義檢索 ( Semantic Search )：根據當前情境找到最相關的歷史記憶
    2. 時間過濾：可按 day range 過濾
    3. 類型過濾：可按 action_type 過濾
    
    使用範例：
        mm = MemoryManager(persist_dir="./chroma_data")
        mm.init_simulation("sim_001")
        mm.save_episodic_memory("hawker_01", 1, "嘈雜夜市", action)
        results = mm.retrieve_relevant_memory("hawker_01", "噪音太大要投訴")
    """
    
    def __init__(
        self,
        persist_dir: str = "./chroma_data",
        embedding_model: str = "all-MiniLM-L6-v2",
        collection_prefix: str = "simulation"
    ):
        """
        初始化記憶管理器
        
        Args:
            persist_dir: ChromaDB 持久化目錄
            embedding_model: Sentence-Transformers 嵌入模型名稱
                           可使用 DeepSeek Embedding API 替換
            collection_prefix: Collection 名稱前綴
        """
        self.persist_dir = persist_dir
        self.collection_prefix = collection_prefix
        
        # 確保持久化目錄存在
        os.makedirs(persist_dir, exist_ok=True)
        
        # 初始化 ChromaDB 客戶端 (持久化模式)
        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        
        # 嵌入函數 — 使用輕量級本地模型，避免 API 調用延遲
        # 可替換為 DeepSeekEmbeddingFunction 用於更高質量的向量
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=embedding_model
        )
        
        # 當前活躍的 collection
        self._active_collection = None
        self._active_simulation_id: Optional[str] = None
    
    # ------------------------------------------------------------------
    #  Collection 生命週期管理
    # ------------------------------------------------------------------
    
    def init_simulation(self, simulation_id: str) -> None:
        """
        為指定模擬初始化獨立的 ChromaDB Collection
        
        每個模擬 (simulation) 擁有獨立的 Collection，
        確保不同沙盤之間的記憶互不污染。
        
        Args:
            simulation_id: 模擬唯一識別碼 (對應 SimulationConfig.simulation_id)
        """
        collection_name = f"{self.collection_prefix}_{simulation_id}"
        
        # 若 Collection 已存在則載入，否則新建
        try:
            self._active_collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_fn
            )
        except Exception:
            self._active_collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.embedding_fn,
                metadata={
                    "simulation_id": simulation_id,
                    "description": "智能體情景記憶集合"
                }
            )
        
        self._active_simulation_id = simulation_id
        print(f"[MemoryManager] 已初始化模擬 '{simulation_id}' 的記憶庫 "
              f"(collection: {collection_name})")
    
    def clear_simulation(self, simulation_id: Optional[str] = None) -> None:
        """
        清除指定模擬的所有記憶
        
        Args:
            simulation_id: 模擬 ID，若不指定則清除當前活躍的
        """
        target_id = simulation_id or self._active_simulation_id
        if not target_id:
            raise ValueError("未指定 simulation_id 且無活躍模擬")
        
        collection_name = f"{self.collection_prefix}_{target_id}"
        try:
            self.client.delete_collection(name=collection_name)
            print(f"[MemoryManager] 已清除模擬 '{target_id}' 的記憶庫")
        except Exception:
            pass  # Collection 可能不存在
        
        if target_id == self._active_simulation_id:
            self._active_collection = None
            self._active_simulation_id = None
    
    def list_simulations(self) -> List[str]:
        """列出所有已存在的模擬記憶庫"""
        collections = self.client.list_collections()
        prefix = f"{self.collection_prefix}_"
        return [
            c.name[len(prefix):]
            for c in collections
            if c.name.startswith(prefix)
        ]
    
    # ------------------------------------------------------------------
    #  記憶寫入 (取代舊版 ObjInfo.upd)
    # ------------------------------------------------------------------
    
    def save_episodic_memory(
        self,
        agent_id: str,
        day: int,
        context: str,
        action: AgentAction,
        emotion: str = "neutral"
    ) -> str:
        """
        將一條情景記憶向量化並存入 ChromaDB
        
        對比舊版：ObjInfo.upd(no, P, D, M) 僅將 M 字串覆蓋，
        舊記憶完全丟失。此方法則累積保存所有歷史記憶。
        
        Args:
            agent_id: 智能體 ID
            day: 當前模擬日
            context: 當天環境情境摘要 (如 "深水埗夜市，人潮擁擠，噪音85分貝")
            action: 智能體行動記錄 (AgentAction)
            emotion: 當前情緒狀態
        
        Returns:
            寫入的記憶 ID
        """
        if self._active_collection is None:
            raise RuntimeError(
                "尚未初始化模擬記憶庫！請先調用 init_simulation(simulation_id)"
            )
        
        document, metadata, memory_id = EpisodicMemory.build(
            agent_id=agent_id,
            day=day,
            context=context,
            action=action,
            emotion=emotion
        )
        
        # 寫入 ChromaDB
        self._active_collection.add(
            documents=[document],
            metadatas=[metadata],
            ids=[memory_id]
        )
        
        return memory_id
    
    def save_batch_memories(
        self,
        memory_batch: List[Dict[str, Any]]
    ) -> List[str]:
        """
        批次寫入多條記憶（效能優化）
        
        Args:
            memory_batch: 每項含 agent_id, day, context, action (AgentAction), emotion
        
        Returns:
            寫入的記憶 ID 列表
        """
        if self._active_collection is None:
            raise RuntimeError("尚未初始化模擬記憶庫！")
        
        documents = []
        metadatas = []
        ids = []
        
        for item in memory_batch:
            doc, meta, mid = EpisodicMemory.build(
                agent_id=item["agent_id"],
                day=item["day"],
                context=item.get("context", ""),
                action=item["action"],
                emotion=item.get("emotion", "neutral")
            )
            documents.append(doc)
            metadatas.append(meta)
            ids.append(mid)
        
        self._active_collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        
        return ids
    
    # ------------------------------------------------------------------
    #  記憶檢索 (全新能力 — 舊版完全不存在)
    # ------------------------------------------------------------------
    
    def retrieve_relevant_memory(
        self,
        agent_id: str,
        current_situation: str,
        top_k: int = 5,
        filter_day_range: Optional[tuple[int, int]] = None,
        filter_action_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        根據當前情境，檢索最相關的 Top-K 歷史記憶
        
        這是舊版 ObjInfo 完全沒有的能力。舊版智能體只能看到
        「上一次更新後的單一記憶字串」，而現在可以根據語義相似度
        找到最相關的歷史經歷。
        
        使用場景：在 perceive_node 中，智能體根據當前環境狀態
        (如「噪音很大」) 檢索過去相關經驗 (如「三年前也遇到噪音，
        當時投訴後獲得賠償」)，從而做出更合理的決策。
        
        Args:
            agent_id: 智能體 ID
            current_situation: 當前情境的自然語言描述 (用於語義匹配)
            top_k: 返回最相關的 K 條記憶
            filter_day_range: 可選的時間範圍過濾 (start_day, end_day)
            filter_action_types: 可選的行動類型過濾
        
        Returns:
            相關記憶列表，每項含 document, metadata, distance
        """
        if self._active_collection is None:
            raise RuntimeError("尚未初始化模擬記憶庫！")
        
        # 構建 ChromaDB where 過濾條件
        where_filter = {"agent_id": agent_id}
        
        if filter_day_range:
            where_filter["day"] = {
                "$gte": filter_day_range[0],
                "$lte": filter_day_range[1]
            }
        
        if filter_action_types:
            where_filter["action_type"] = {
                "$in": filter_action_types
            }
        
        # 執行語義查詢
        results = self._active_collection.query(
            query_texts=[current_situation],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )
        
        # 格式化返回結果
        memories = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                memories.append({
                    "id": results["ids"][0][i],
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "relevance_score": 1.0 - results["distances"][0][i],
                })
        
        return memories
    
    def get_agent_memory_count(self, agent_id: str) -> int:
        """
        獲取指定智能體的記憶總數
        
        用於監控記憶膨脹，或判斷是否需要觸發記憶壓縮 (compaction)
        """
        if self._active_collection is None:
            return 0
        
        results = self._active_collection.get(
            where={"agent_id": agent_id},
            include=[]
        )
        return len(results["ids"]) if results["ids"] else 0
    
    def get_agent_memories_by_day(
        self, agent_id: str, day: int
    ) -> List[Dict[str, Any]]:
        """
        獲取指定智能體在特定模擬日的所有記憶
        
        用於除錯或生成每日摘要
        """
        if self._active_collection is None:
            return []
        
        results = self._active_collection.get(
            where={
                "agent_id": agent_id,
                "day": day
            },
            include=["documents", "metadatas"]
        )
        
        memories = []
        if results["ids"]:
            for i in range(len(results["ids"])):
                memories.append({
                    "id": results["ids"][i],
                    "document": results["documents"][i],
                    "metadata": results["metadatas"][i],
                })
        
        return memories


# ============================================================
#  便捷工廠函數
# ============================================================

def create_memory_manager(
    persist_dir: str = "./chroma_data",
    embedding_model: str = "all-MiniLM-L6-v2"
) -> MemoryManager:
    """
    創建 MemoryManager 實例的工廠函數
    
    預設使用 all-MiniLM-L6-v2 作為嵌入模型 (384 維, 約 80MB)。
    如需更高質量，可替換為：
    - "intfloat/multilingual-e5-large" (支援多語言, 1024 維)
    - 或使用 DeepSeek Embedding API 的自定義 wrapper
    """
    return MemoryManager(
        persist_dir=persist_dir,
        embedding_model=embedding_model
    )


# ============================================================
#  自我測試 (開發期間用)
# ============================================================

if __name__ == "__main__":
    print("=== ChromaDB 記憶管理器自我測試 ===\n")
    
    # 建立一個假的 AgentAction 用於測試
    from models import AgentAction as AA
    
    test_action = AA(
        agent_id="hawker_01",
        day=1,
        timestamp="2008-01-01T10:00:00",
        action_type="complain",
        action_description="陳伯向城管大聲投訴夜市噪音過大，影響其生意",
        duration_minutes=15,
        environment_effects={"noise_level": 0.02, "social_stability": -0.01}
    )
    
    # 初始化記憶管理器
    mm = create_memory_manager(persist_dir="./test_chroma_data")
    mm.init_simulation("test_sim_001")
    
    # 測試寫入
    memory_id = mm.save_episodic_memory(
        agent_id="hawker_01",
        day=1,
        context="深水埗夜市，週五晚上，人潮密度 0.7，噪音水平 0.65",
        action=test_action,
        emotion="angry"
    )
    print(f"✅ 寫入記憶: {memory_id}")
    
    # 寫入更多測試記憶
    test_action2 = AA(
        agent_id="hawker_01",
        day=2,
        timestamp="2008-01-02T14:00:00",
        action_type="trade",
        action_description="陳伯降價促銷魚蛋，成功吸引一批學生顧客",
        duration_minutes=60,
        environment_effects={"economic_activity": 0.03}
    )
    mm.save_episodic_memory(
        agent_id="hawker_01",
        day=2,
        context="深水埗夜市，週六下午，人潮密度 0.5，經濟活躍度 0.4",
        action=test_action2,
        emotion="happy"
    )
    
    test_action3 = AA(
        agent_id="hawker_01",
        day=3,
        timestamp="2008-01-03T20:00:00",
        action_type="interact",
        action_description="陳伯與鄰近菜販阿姐閒聊，抱怨近日人客減少",
        duration_minutes=10,
        target_agent_id="vendor_02",
        environment_effects={}
    )
    mm.save_episodic_memory(
        agent_id="hawker_01",
        day=3,
        context="深水埗夜市，週日晚上，人潮密度 0.3，經濟活躍度 0.3",
        action=test_action3,
        emotion="anxious"
    )
    
    # 測試檢索
    print(f"\n📊 智能體 hawker_01 總記憶數: {mm.get_agent_memory_count('hawker_01')}")
    
    print("\n🔍 檢索情境: 「夜市太吵，生意難做」")
    results = mm.retrieve_relevant_memory(
        agent_id="hawker_01",
        current_situation="夜市太吵，生意難做，收入減少",
        top_k=3
    )
    
    for i, r in enumerate(results, 1):
        print(f"\n  [{i}] 相關度: {r['relevance_score']:.3f}")
        print(f"      記憶: {r['document'][:80]}...")
        print(f"      日期: Day {r['metadata']['day']}, "
              f"行動類型: {r['metadata']['action_type']}")
    
    # 清理測試數據
    mm.clear_simulation("test_sim_001")
    print("\n✅ 測試完成，已清理測試數據")
