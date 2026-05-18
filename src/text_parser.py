import re
import json
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class Line:
    """台词数据类"""
    character: Optional[str]  # 角色名称，None表示旁白
    content: str             # 台词内容
    order: int               # 顺序
    emotion: Optional[str] = None  # 情感（可选）


class TextParser:
    """文本解析器，用于识别小说中的角色和台词"""
    
    def __init__(self):
        # 匹配 [角色名] 台词 的格式
        self.bracket_pattern = re.compile(r'^\s*\[([^\]]+)\]\s*(.+)$')
        # 匹配 角色名：台词 的格式
        self.colon_pattern = re.compile(r'^\s*([^：:]+)[：:]\s*(.+)$')
        # 匹配 "角色名"说 的格式
        self.said_pattern = re.compile(r'["「]([^"」]+)["」]\s*(?:说|道|喊|叫|问|回答|说道|喊道|叫道|问道|回答道)\s*[，,。]?\s*(.+)$')
        
    def parse_text(self, text: str) -> List[Line]:
        """
        解析文本，识别角色和台词
        
        Args:
            text: 输入的文本内容
            
        Returns:
            List[Line]: 解析后的台词列表
        """
        lines = []
        current_order = 0
        
        # 按行分割
        for line_text in text.split('\n'):
            line_text = line_text.strip()
            if not line_text:
                continue
            
            # 尝试匹配 [角色名] 格式
            match = self.bracket_pattern.match(line_text)
            if match:
                character = match.group(1).strip()
                content = match.group(2).strip()
                lines.append(Line(
                    character=character if character != '旁白' else None,
                    content=content,
                    order=current_order
                ))
                current_order += 1
                continue
            
            # 尝试匹配 角色名：台词 格式
            match = self.colon_pattern.match(line_text)
            if match:
                character = match.group(1).strip()
                content = match.group(2).strip()
                lines.append(Line(
                    character=character,
                    content=content,
                    order=current_order
                ))
                current_order += 1
                continue
            
            # 尝试匹配 "角色名"说 格式
            match = self.said_pattern.match(line_text)
            if match:
                character = match.group(1).strip()
                content = match.group(2).strip()
                lines.append(Line(
                    character=character,
                    content=content,
                    order=current_order
                ))
                current_order += 1
                continue
            
            # 如果没有匹配到角色格式，视为旁白
            lines.append(Line(
                character=None,
                content=line_text,
                order=current_order
            ))
            current_order += 1
        
        return lines
    
    def extract_characters(self, lines: List[Line]) -> Dict[str, int]:
        """
        从台词列表中提取角色信息
        
        Args:
            lines: 台词列表
            
        Returns:
            Dict[str, int]: 角色名称和出现次数的字典
        """
        characters = {}
        for line in lines:
            if line.character is not None:
                characters[line.character] = characters.get(line.character, 0) + 1
        return characters
    
    def auto_assign_voices(self, characters: Dict[str, int], available_voices: List[str]) -> Dict[str, str]:
        """
        自动为角色分配声音
        
        Args:
            characters: 角色名称和出现次数的字典
            available_voices: 可用的声音列表
            
        Returns:
            Dict[str, str]: 角色名称和分配的声音的映射
        """
        assignments = {}
        sorted_characters = sorted(characters.items(), key=lambda x: x[1], reverse=True)
        
        for i, (character, _) in enumerate(sorted_characters):
            if i < len(available_voices):
                assignments[character] = available_voices[i]
            else:
                # 如果声音不够，循环使用
                assignments[character] = available_voices[i % len(available_voices)]
        
        return assignments


# 预置声音列表（Qwen3-TTS默认提供的9个声音）
PREDEFINED_VOICES = [
    "Vivian",
    "Serena", 
    "Uncle_Fu",
    "Dylan",
    "Eric",
    "Ryan",
    "Aiden",
    "Ono_Anna",
    "Sohee"
]


def parse_novel_text(text: str) -> Tuple[List[Line], Dict[str, int]]:
    """
    解析小说文本，返回台词列表和角色统计
    
    Args:
        text: 小说文本
        
    Returns:
        Tuple[List[Line], Dict[str, int]]: (台词列表, 角色统计)
    """
    parser = TextParser()
    lines = parser.parse_text(text)
    characters = parser.extract_characters(lines)
    return lines, characters


def auto_assign_voices_to_characters(characters: Dict[str, int], available_voices: List[str] = None) -> Dict[str, str]:
    """
    自动为角色分配预置声音
    
    Args:
        characters: 角色名称和出现次数的字典
        available_voices: 可用的声音列表（可选）
        
    Returns:
        Dict[str, str]: 角色名称和分配的声音的映射
    """
    parser = TextParser()
    voices = available_voices if available_voices else PREDEFINED_VOICES
    return parser.auto_assign_voices(characters, voices)


if __name__ == "__main__":
    # 测试文本解析
    test_text = """
[旁白] 刺骨的寒意像无数根细密的钢针，疯狂地扎进骨髓深处。
[苏苏] 林晚，别怪我们，要怪就怪你命不好，挡了我们的路。
[苏苏] 快给她灌下去！这药吃多了，神仙也查不出死因，只会以为是抑郁症发作！
[林晚] 啊——！
[顾城] 晚晚，怎么了？做噩梦了吗？
[林晚] 老公……我梦见……梦见你不要我了。
[顾城] 傻瓜，今天是我们的三周年纪念日，我疼你都来不及，怎么会不要你？
"""
    
    lines, characters = parse_novel_text(test_text)
    print("解析结果：")
    for line in lines:
        char = line.character if line.character else "旁白"
        print(f"[{char}] {line.content}")
    
    print("\n角色统计：")
    for char, count in characters.items():
        print(f"  {char}: {count}次")
    
    print("\n自动分配声音：")
    assignments = auto_assign_voices_to_characters(characters)
    for char, voice in assignments.items():
        print(f"  {char} -> {voice}")
