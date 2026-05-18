import os
import json
import sqlite3
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict
from pathlib import Path


# 数据模型
@dataclass
class Project:
    id: Optional[int]
    name: str
    created_at: str
    updated_at: str
    status: str  # pending/processing/completed
    text_content: str = ""  # 原始文本内容


@dataclass
class Character:
    id: Optional[int]
    project_id: int
    name: str
    voice_id: Optional[int]
    description: Optional[str] = None


@dataclass
class Line:
    id: Optional[int]
    project_id: int
    character_id: Optional[int]  # None表示旁白
    content: str
    order: int
    emotion: Optional[str] = None


@dataclass
class Voice:
    id: Optional[int]
    name: str
    voice_type: str  # predefined/design/clone
    description: Optional[str] = None
    speaker: Optional[str] = None  # 预置声音名称
    instruct: Optional[str] = None  # 声音设计描述
    ref_audio_path: Optional[str] = None  # 参考音频路径
    ref_text: Optional[str] = None  # 参考文本
    emotion: Optional[str] = None  # 默认情感/风格描述
    created_at: str = ""


@dataclass
class AudioSegment:
    id: Optional[int]
    project_id: int
    line_id: int
    character_id: Optional[int]
    audio_path: str
    duration: Optional[float] = None


class Database:
    """SQLite数据库管理类"""
    
    def __init__(self, db_path: str = "novel_tts.db"):
        self.db_path = db_path
        self._shared_memory = False
        self._connection = None
        
        # 对于内存数据库，使用共享缓存模式
        if db_path == ':memory:':
            self.db_path = 'file:novel_tts?mode=memory&cache=shared'
            self._shared_memory = True
        
        self.init_database()
    
    def get_connection(self):
        """获取数据库连接"""
        if self._shared_memory:
            # 对于内存数据库，保持连接打开
            if self._connection is None:
                self._connection = sqlite3.connect(self.db_path, uri=True)
            return self._connection
        return sqlite3.connect(self.db_path)
    
    def close_connection(self):
        """关闭数据库连接"""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
    
    def init_database(self):
        """初始化数据库表"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 项目表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                text_content TEXT DEFAULT ''
            )
        ''')
        
        # 角色表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                voice_id INTEGER,
                description TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        ''')
        
        # 台词表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                character_id INTEGER,
                content TEXT NOT NULL,
                order_num INTEGER NOT NULL,
                emotion TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE SET NULL
            )
        ''')
        
        # 声音表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS voices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                voice_type TEXT NOT NULL,
                description TEXT,
                speaker TEXT,
                instruct TEXT,
                ref_audio_path TEXT,
                ref_text TEXT,
                emotion TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        
        # 音频片段表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audio_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                line_id INTEGER NOT NULL,
                character_id INTEGER,
                audio_path TEXT NOT NULL,
                duration REAL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (line_id) REFERENCES lines(id) ON DELETE CASCADE
            )
        ''')
        
        self._migrate_schema(cursor)
        conn.commit()
        # 对于内存数据库，不要关闭连接
        if not self._shared_memory:
            conn.close()
        
        # 初始化预置声音
        self.init_predefined_voices()

    def _migrate_schema(self, cursor):
        """数据库 schema 迁移"""
        cursor.execute("PRAGMA table_info(voices)")
        voice_cols = {row[1] for row in cursor.fetchall()}
        if "emotion" not in voice_cols:
            cursor.execute("ALTER TABLE voices ADD COLUMN emotion TEXT")
    
    def init_predefined_voices(self):
        """初始化预置声音"""
        predefined_voices = [
            Voice(id=None, name="Vivian", voice_type="predefined", description="明亮、略带锐利的年轻女声", speaker="Vivian", created_at=datetime.now().isoformat()),
            Voice(id=None, name="Serena", voice_type="predefined", description="温暖、温柔的年轻女声", speaker="Serena", created_at=datetime.now().isoformat()),
            Voice(id=None, name="Uncle_Fu", voice_type="predefined", description="低沉、醇厚的成熟男声", speaker="Uncle_Fu", created_at=datetime.now().isoformat()),
            Voice(id=None, name="Dylan", voice_type="predefined", description="年轻、清晰的北京男声", speaker="Dylan", created_at=datetime.now().isoformat()),
            Voice(id=None, name="Eric", voice_type="predefined", description="活泼、略带沙哑的成都男声", speaker="Eric", created_at=datetime.now().isoformat()),
            Voice(id=None, name="Ryan", voice_type="predefined", description="富有节奏感的动态男声", speaker="Ryan", created_at=datetime.now().isoformat()),
            Voice(id=None, name="Aiden", voice_type="predefined", description="阳光、清晰的美式男声", speaker="Aiden", created_at=datetime.now().isoformat()),
            Voice(id=None, name="Ono_Anna", voice_type="predefined", description="活泼、轻快的日本女声", speaker="Ono_Anna", created_at=datetime.now().isoformat()),
            Voice(id=None, name="Sohee", voice_type="predefined", description="温暖、富有情感的韩国女声", speaker="Sohee", created_at=datetime.now().isoformat()),
        ]
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # 检查是否已有预置声音
            cursor.execute("SELECT COUNT(*) FROM voices WHERE voice_type = 'predefined'")
            count = cursor.fetchone()[0]
            
            if count == 0:
                for voice in predefined_voices:
                    cursor.execute('''
                        INSERT INTO voices (name, voice_type, description, speaker, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (voice.name, voice.voice_type, voice.description, voice.speaker, voice.created_at))
                conn.commit()
        except sqlite3.OperationalError as e:
            # 表不存在时跳过
            if "no such table" in str(e):
                pass
            else:
                raise
        finally:
            # 对于非内存数据库，关闭连接
            if not self._shared_memory:
                conn.close()
    
    # 项目操作
    def create_project(self, name: str, text_content: str = "") -> int:
        """创建项目"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
            INSERT INTO projects (name, created_at, updated_at, status, text_content)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, now, now, 'pending', text_content))
        project_id = cursor.lastrowid
        conn.commit()
        # 对于非内存数据库，关闭连接
        if not self._shared_memory:
            conn.close()
        return project_id
    
    def get_project(self, project_id: int) -> Optional[Project]:
        """获取项目"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return Project(id=row[0], name=row[1], created_at=row[2], updated_at=row[3], status=row[4], text_content=row[5])
        return None
    
    def get_all_projects(self) -> List[Project]:
        """获取所有项目"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM projects ORDER BY created_at DESC')
        rows = cursor.fetchall()
        conn.close()
        return [Project(id=row[0], name=row[1], created_at=row[2], updated_at=row[3], status=row[4], text_content=row[5]) for row in rows]
    
    def update_project_status(self, project_id: int, status: str):
        """更新项目状态"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('UPDATE projects SET status = ?, updated_at = ? WHERE id = ?', (status, now, project_id))
        conn.commit()
        conn.close()
    
    def delete_project(self, project_id: int):
        """删除项目"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
        conn.commit()
        conn.close()

    def clear_project_parsed_data(self, project_id: int):
        """清除项目的解析数据（角色、台词、音频片段）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM audio_segments WHERE project_id = ?', (project_id,))
        cursor.execute('DELETE FROM lines WHERE project_id = ?', (project_id,))
        cursor.execute('DELETE FROM characters WHERE project_id = ?', (project_id,))
        conn.commit()
        if not self._shared_memory:
            conn.close()
    
    # 角色操作
    def create_character(self, project_id: int, name: str, voice_id: Optional[int] = None, description: Optional[str] = None) -> int:
        """创建角色"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO characters (project_id, name, voice_id, description)
            VALUES (?, ?, ?, ?)
        ''', (project_id, name, voice_id, description))
        character_id = cursor.lastrowid
        conn.commit()
        # 对于非内存数据库，关闭连接
        if not self._shared_memory:
            conn.close()
        return character_id
    
    def get_project_characters(self, project_id: int) -> List[Character]:
        """获取项目的所有角色"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM characters WHERE project_id = ?', (project_id,))
        rows = cursor.fetchall()
        conn.close()
        return [Character(id=row[0], project_id=row[1], name=row[2], voice_id=row[3], description=row[4]) for row in rows]
    
    def update_character_voice(self, character_id: int, voice_id: Optional[int]):
        """更新角色声音"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE characters SET voice_id = ? WHERE id = ?', (voice_id, character_id))
        conn.commit()
        conn.close()
    
    # 台词操作
    def create_line(self, project_id: int, character_id: Optional[int], content: str, order: int, emotion: Optional[str] = None) -> int:
        """创建台词"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO lines (project_id, character_id, content, order_num, emotion)
            VALUES (?, ?, ?, ?, ?)
        ''', (project_id, character_id, content, order, emotion))
        line_id = cursor.lastrowid
        conn.commit()
        # 对于非内存数据库，关闭连接
        if not self._shared_memory:
            conn.close()
        return line_id
    
    def get_project_lines(self, project_id: int) -> List[Line]:
        """获取项目的所有台词"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM lines WHERE project_id = ? ORDER BY order_num', (project_id,))
        rows = cursor.fetchall()
        conn.close()
        return [Line(id=row[0], project_id=row[1], character_id=row[2], content=row[3], order=row[4], emotion=row[5]) for row in rows]

    def get_line(self, line_id: int) -> Optional[Line]:
        """获取单条台词"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM lines WHERE id = ?', (line_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return Line(id=row[0], project_id=row[1], character_id=row[2], content=row[3], order=row[4], emotion=row[5])
        return None

    def update_line_emotion(self, line_id: int, emotion: Optional[str]):
        """更新台词情感"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE lines SET emotion = ? WHERE id = ?', (emotion, line_id))
        conn.commit()
        conn.close()
    
    # 声音操作
    def create_voice(self, voice: Voice) -> int:
        """创建声音"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
            INSERT INTO voices (name, voice_type, description, speaker, instruct, ref_audio_path, ref_text, emotion, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (voice.name, voice.voice_type, voice.description, voice.speaker, voice.instruct,
              voice.ref_audio_path, voice.ref_text, voice.emotion, now))
        voice_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return voice_id
    
    def get_voice(self, voice_id: int) -> Optional[Voice]:
        """获取声音"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM voices WHERE id = ?', (voice_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return self._row_to_voice(row)
        return None

    def _row_to_voice(self, row) -> Voice:
        if len(row) >= 10:
            return Voice(
                id=row[0], name=row[1], voice_type=row[2], description=row[3],
                speaker=row[4], instruct=row[5], ref_audio_path=row[6], ref_text=row[7],
                emotion=row[8], created_at=row[9] or ""
            )
        return Voice(
            id=row[0], name=row[1], voice_type=row[2], description=row[3],
            speaker=row[4], instruct=row[5], ref_audio_path=row[6], ref_text=row[7],
            emotion=None, created_at=row[8] or ""
        )
    
    def get_all_voices(self) -> List[Voice]:
        """获取所有声音"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM voices ORDER BY created_at DESC')
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_voice(row) for row in rows]

    def update_voice(self, voice_id: int, **fields):
        """更新声音信息"""
        allowed = {"name", "description", "instruct", "emotion", "speaker", "ref_text", "ref_audio_path"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        conn = self.get_connection()
        cursor = conn.cursor()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [voice_id]
        cursor.execute(f'UPDATE voices SET {set_clause} WHERE id = ?', values)
        conn.commit()
        conn.close()
    
    def delete_voice(self, voice_id: int):
        """删除声音"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM voices WHERE id = ?', (voice_id,))
        conn.commit()
        conn.close()
    
    # 音频片段操作
    def create_audio_segment(self, project_id: int, line_id: int, character_id: Optional[int], audio_path: str, duration: Optional[float] = None) -> int:
        """创建音频片段"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO audio_segments (project_id, line_id, character_id, audio_path, duration)
            VALUES (?, ?, ?, ?, ?)
        ''', (project_id, line_id, character_id, audio_path, duration))
        segment_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return segment_id
    
    def get_project_audio_segments(self, project_id: int) -> List[AudioSegment]:
        """获取项目的所有音频片段"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM audio_segments WHERE project_id = ? ORDER BY line_id', (project_id,))
        rows = cursor.fetchall()
        conn.close()
        return [AudioSegment(id=row[0], project_id=row[1], line_id=row[2], character_id=row[3], audio_path=row[4], duration=row[5]) for row in rows]

    def get_audio_segment_by_line(self, line_id: int) -> Optional[AudioSegment]:
        """获取台词对应的音频片段"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM audio_segments WHERE line_id = ? ORDER BY id DESC LIMIT 1',
            (line_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return AudioSegment(id=row[0], project_id=row[1], line_id=row[2], character_id=row[3], audio_path=row[4], duration=row[5])
        return None

    def upsert_audio_segment(self, project_id: int, line_id: int, character_id: Optional[int],
                             audio_path: str, duration: Optional[float] = None) -> int:
        """更新或插入音频片段"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM audio_segments WHERE line_id = ?', (line_id,))
        cursor.execute('''
            INSERT INTO audio_segments (project_id, line_id, character_id, audio_path, duration)
            VALUES (?, ?, ?, ?, ?)
        ''', (project_id, line_id, character_id, audio_path, duration))
        segment_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return segment_id


# 全局数据库实例
db = Database()
