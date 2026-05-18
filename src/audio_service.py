"""音频生成业务逻辑"""
import os
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from .database import db, Character, Line, Voice
from .audio_generator import (
    AudioGenerator, VoiceConfig, get_audio_generator,
    merge_audio_segments, save_audio
)
from .config_manager import config


NARRATOR_NAME = "旁白"


def get_inference_kwargs() -> dict:
    """从配置读取模型推理参数"""
    return {
        "temperature": config.get("temperature", 0.9),
        "top_p": config.get("top_p", 1.0),
        "top_k": config.get("top_k", 50),
        "repetition_penalty": config.get("repetition_penalty", 1.05),
        "max_new_tokens": config.get("max_new_tokens", 2048),
    }


def voice_to_config(voice: Voice) -> VoiceConfig:
    return VoiceConfig(
        id=voice.id,
        name=voice.name,
        voice_type=voice.voice_type,
        speaker=voice.speaker,
        instruct=voice.instruct,
        ref_audio_path=voice.ref_audio_path,
        ref_text=voice.ref_text,
        emotion=voice.emotion,
    )


def build_instruct(voice: Voice, line_emotion: Optional[str] = None) -> str:
    """合并声音默认情感与台词情感为 instruct"""
    parts = []
    if voice.emotion:
        parts.append(voice.emotion.strip())
    if line_emotion and line_emotion.strip():
        parts.append(line_emotion.strip())
    if voice.voice_type == "design" and voice.instruct:
        parts.insert(0, voice.instruct.strip())
    return "，".join(parts) if parts else ""


def generate_line_audio(
    project_id: int,
    line: Line,
    character_map: Dict[int, Character],
    generator: Optional[AudioGenerator] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    为单条台词生成音频。
    返回 (audio_path, error_message)
    """
    gen = generator or get_audio_generator()
    inference_kw = get_inference_kwargs()

    char = character_map.get(line.character_id) if line.character_id else None
    if not char or not char.voice_id:
        return None, "角色未绑定声音"

    voice = db.get_voice(char.voice_id)
    if not voice:
        return None, "声音不存在"

    voice_config = voice_to_config(voice)
    instruct = build_instruct(voice, line.emotion)

    try:
        if voice.voice_type == "predefined":
            audio, sr = gen.generate_custom_voice(
                text=line.content,
                speaker=voice.speaker,
                language=config.get("language", "Chinese"),
                instruct=instruct or None,
                **inference_kw,
            )
        elif voice.voice_type == "design":
            design_instruct = instruct or voice.instruct or voice.emotion or ""
            audio, sr = gen.generate_voice_design(
                text=line.content,
                instruct=design_instruct,
                language=config.get("language", "Chinese"),
                **inference_kw,
            )
        elif voice.voice_type == "clone":
            audio, sr = gen.generate_voice_clone(
                text=line.content,
                ref_audio_path=voice.ref_audio_path,
                ref_text=voice.ref_text,
                language=config.get("language", "Chinese"),
                **inference_kw,
            )
        else:
            return None, f"未知声音类型: {voice.voice_type}"

        output_path = f"static/audio/project_{project_id}_line_{line.id}.wav"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        save_audio(audio, sr, output_path)
        duration = len(audio) / sr
        db.upsert_audio_segment(project_id, line.id, line.character_id, output_path, duration)
        return output_path, None
    except Exception as e:
        return None, str(e)


def generate_project_all(project_id: int) -> dict:
    """批量生成项目全部台词音频并合并"""
    lines = db.get_project_lines(project_id)
    if not lines:
        return {"success": 0, "failed": 0, "errors": ["项目没有台词"]}

    characters = db.get_project_characters(project_id)
    character_map = {c.id: c for c in characters}
    generator = get_audio_generator()
    db.update_project_status(project_id, "generating")

    audio_segments: List[Tuple[np.ndarray, int]] = []
    errors = []
    success = 0
    failed = 0

    for line in lines:
        path, err = generate_line_audio(project_id, line, character_map, generator)
        if path:
            success += 1
            import soundfile as sf
            audio, sr = sf.read(path)
            audio_segments.append((audio, sr))
        else:
            failed += 1
            errors.append(f"第{line.order + 1}行: {err}")

    if audio_segments:
        merged_path = f"static/audio/project_{project_id}_merged.wav"
        merge_audio_segments(audio_segments, merged_path)

    db.update_project_status(project_id, "completed" if success else "parsed")
    return {"success": success, "failed": failed, "errors": errors[:20]}


def parse_and_assign_voices(project_id: int, text_content: str) -> dict:
    """解析文本、创建角色与台词、自动分配声音"""
    from .text_parser import parse_novel_text, auto_assign_voices_to_characters

    db.clear_project_parsed_data(project_id)
    lines, characters = parse_novel_text(text_content)

    has_narration = any(l.character is None for l in lines)
    if has_narration:
        characters[NARRATOR_NAME] = characters.get(NARRATOR_NAME, 0) + sum(
            1 for l in lines if l.character is None
        )

    character_ids = {}
    for char_name in characters.keys():
        character_ids[char_name] = db.create_character(project_id, char_name)

    for line in lines:
        char_name = line.character if line.character else NARRATOR_NAME
        char_id = character_ids.get(char_name)
        db.create_line(project_id, char_id, line.content, line.order, line.emotion)

    available_voices = db.get_all_voices()
    voice_names = [v.name for v in available_voices]
    assignments = auto_assign_voices_to_characters(characters, voice_names)

    name_to_voice = {v.name: v for v in available_voices}
    for char_name, voice_name in assignments.items():
        char_id = character_ids.get(char_name)
        voice = name_to_voice.get(voice_name)
        if char_id and voice:
            db.update_character_voice(char_id, voice.id)

    db.update_project_status(project_id, "parsed")
    return {
        "characters": list(characters.keys()),
        "lines_count": len(lines),
        "assignments": assignments,
    }
