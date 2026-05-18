from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import os
import json
import time
from typing import List, Optional

from src.database import db, Project, Character, Line, Voice, AudioSegment
from src.text_parser import TextParser, parse_novel_text, auto_assign_voices_to_characters
from src.audio_generator import AudioGenerator, VoiceConfig, get_audio_generator, merge_audio_segments, save_audio
from src.config_manager import config
from src.logger import setup_logger, log_system_info, log_performance_metrics, log_time

# 初始化日志
logger = setup_logger(
    name="novel_tts",
    log_level="INFO",
    log_file="logs/novel_tts.log",
    console_output=True,
    file_output=True
)

# 记录系统信息
log_system_info()

app = FastAPI(title="小说多角色语音合成系统")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 创建静态文件目录
os.makedirs("static/audio", exist_ok=True)
os.makedirs("static/uploads", exist_ok=True)


# ========== 项目API ==========

@app.post("/api/projects")
async def create_project(name: str = Form(...), text_content: str = Form(...)):
    """创建项目"""
    logger.info(f"创建项目: name={name}, text_length={len(text_content)}")
    start_time = time.time()
    
    try:
        project_id = db.create_project(name, text_content)
        duration = time.time() - start_time
        logger.info(f"项目创建成功: id={project_id}, 耗时: {duration:.2f}秒")
        return {"id": project_id, "name": name, "status": "pending"}
    except Exception as e:
        logger.error(f"项目创建失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects")
async def get_projects():
    """获取所有项目"""
    logger.info("获取项目列表")
    start_time = time.time()
    
    try:
        projects = db.get_all_projects()
        duration = time.time() - start_time
        logger.info(f"获取项目列表成功: 共 {len(projects)} 个项目, 耗时: {duration:.2f}秒")
        return [{"id": p.id, "name": p.name, "status": p.status, "created_at": p.created_at} for p in projects]
    except Exception as e:
        logger.error(f"获取项目列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}")
async def get_project(project_id: int):
    """获取项目详情"""
    logger.info(f"获取项目详情: id={project_id}")
    
    try:
        project = db.get_project(project_id)
        if not project:
            logger.warning(f"项目不存在: id={project_id}")
            raise HTTPException(status_code=404, detail="项目不存在")
        return {"id": project.id, "name": project.name, "status": project.status, "text_content": project.text_content}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取项目详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int):
    """删除项目"""
    logger.info(f"删除项目: id={project_id}")
    
    try:
        db.delete_project(project_id)
        logger.info(f"项目删除成功: id={project_id}")
        return {"message": "项目已删除"}
    except Exception as e:
        logger.error(f"删除项目失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 文本解析API ==========

@app.post("/api/projects/{project_id}/parse")
async def parse_project_text(project_id: int):
    """解析项目文本"""
    logger.info(f"解析项目文本: id={project_id}")
    start_time = time.time()
    
    try:
        project = db.get_project(project_id)
        if not project:
            logger.warning(f"项目不存在: id={project_id}")
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 解析文本
        lines, characters = parse_novel_text(project.text_content)
        logger.info(f"文本解析完成: 共 {len(lines)} 行台词, {len(characters)} 个角色")
        
        # 创建角色
        character_ids = {}
        for char_name in characters.keys():
            char_id = db.create_character(project_id, char_name)
            character_ids[char_name] = char_id
        
        # 创建台词
        for line in lines:
            char_id = character_ids.get(line.character) if line.character else None
            db.create_line(project_id, char_id, line.content, line.order, line.emotion)
        
        # 自动分配声音
        available_voices = db.get_all_voices()
        voice_names = [v.name for v in available_voices]
        assignments = auto_assign_voices_to_characters(characters, voice_names)
        
        # 更新角色声音绑定
        for char_name, voice_name in assignments.items():
            char_id = character_ids[char_name]
            for voice in available_voices:
                if voice.name == voice_name:
                    db.update_character_voice(char_id, voice.id)
                    break
        
        # 更新项目状态
        db.update_project_status(project_id, "parsed")
        
        duration = time.time() - start_time
        logger.info(f"项目解析完成: id={project_id}, 耗时: {duration:.2f}秒")
        
        return {
            "message": "文本解析完成",
            "characters": list(characters.keys()),
            "lines_count": len(lines),
            "assignments": assignments
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"解析项目文本失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 角色管理API ==========

@app.get("/api/projects/{project_id}/characters")
async def get_characters(project_id: int):
    """获取项目角色"""
    logger.info(f"获取项目角色: id={project_id}")
    
    try:
        characters = db.get_project_characters(project_id)
        result = []
        for char in characters:
            voice = db.get_voice(char.voice_id) if char.voice_id else None
            result.append({
                "id": char.id,
                "name": char.name,
                "voice_id": char.voice_id,
                "voice_name": voice.name if voice else None,
                "description": char.description
            })
        logger.info(f"获取角色成功: 共 {len(result)} 个角色")
        return result
    except Exception as e:
        logger.error(f"获取角色失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/projects/{project_id}/characters/{character_id}")
async def update_character(project_id: int, character_id: int, voice_id: int = Form(...)):
    """更新角色声音"""
    logger.info(f"更新角色声音: project_id={project_id}, character_id={character_id}, voice_id={voice_id}")
    
    try:
        db.update_character_voice(character_id, voice_id)
        logger.info(f"角色声音更新成功: character_id={character_id}")
        return {"message": "角色声音已更新"}
    except Exception as e:
        logger.error(f"更新角色声音失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 声音库API ==========

@app.get("/api/voices")
async def get_voices():
    """获取所有声音"""
    logger.info("获取声音列表")
    
    try:
        voices = db.get_all_voices()
        logger.info(f"获取声音成功: 共 {len(voices)} 个声音")
        return [{"id": v.id, "name": v.name, "type": v.voice_type, "description": v.description, "speaker": v.speaker} for v in voices]
    except Exception as e:
        logger.error(f"获取声音失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/voices/design")
async def create_design_voice(name: str = Form(...), description: str = Form(...), instruct: str = Form(...)):
    """创建设计声音"""
    logger.info(f"创建设计声音: name={name}")
    
    try:
        voice = Voice(
            id=None,
            name=name,
            voice_type="design",
            description=description,
            instruct=instruct
        )
        voice_id = db.create_voice(voice)
        logger.info(f"设计声音创建成功: id={voice_id}")
        return {"id": voice_id, "name": name, "type": "design"}
    except Exception as e:
        logger.error(f"创建设计声音失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/voices/clone")
async def create_clone_voice(name: str = Form(...), description: str = Form(...), ref_text: str = Form(...), ref_audio: UploadFile = File(...)):
    """创建克隆声音"""
    logger.info(f"创建克隆声音: name={name}")
    
    try:
        # 保存参考音频
        audio_path = f"static/uploads/{ref_audio.filename}"
        with open(audio_path, "wb") as f:
            shutil.copyfileobj(ref_audio.file, f)
        
        voice = Voice(
            id=None,
            name=name,
            voice_type="clone",
            description=description,
            ref_audio_path=audio_path,
            ref_text=ref_text
        )
        voice_id = db.create_voice(voice)
        logger.info(f"克隆声音创建成功: id={voice_id}")
        return {"id": voice_id, "name": name, "type": "clone"}
    except Exception as e:
        logger.error(f"创建克隆声音失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/voices/{voice_id}")
async def delete_voice(voice_id: int):
    """删除声音"""
    logger.info(f"删除声音: id={voice_id}")
    
    try:
        db.delete_voice(voice_id)
        logger.info(f"声音删除成功: id={voice_id}")
        return {"message": "声音已删除"}
    except Exception as e:
        logger.error(f"删除声音失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/voices/{voice_id}/preview")
async def preview_voice(voice_id: int, text: str = Form("你好，这是一个测试。")):
    """试听声音"""
    logger.info(f"试听声音: id={voice_id}")
    
    try:
        voice = db.get_voice(voice_id)
        if not voice:
            logger.warning(f"声音不存在: id={voice_id}")
            raise HTTPException(status_code=404, detail="声音不存在")
        
        # 生成预览音频
        generator = get_audio_generator()
        voice_config = VoiceConfig(
            id=voice.id,
            name=voice.name,
            voice_type=voice.voice_type,
            speaker=voice.speaker,
            instruct=voice.instruct,
            ref_audio_path=voice.ref_audio_path,
            ref_text=voice.ref_text
        )
        
        audio, sr = generator.generate_with_voice_config(text, voice_config)
        
        # 保存音频
        output_path = f"static/audio/preview_{voice_id}.wav"
        save_audio(audio, sr, output_path)
        
        logger.info(f"预览音频生成成功: id={voice_id}")
        return {"audio_path": output_path}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"试听声音失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 音频生成API ==========

@app.post("/api/projects/{project_id}/generate")
async def generate_project_audio(project_id: int):
    """生成项目音频"""
    logger.info(f"生成项目音频: id={project_id}")
    start_time = time.time()
    
    try:
        project = db.get_project(project_id)
        if not project:
            logger.warning(f"项目不存在: id={project_id}")
            raise HTTPException(status_code=404, detail="项目不存在")
        
        # 获取所有台词
        lines = db.get_project_lines(project_id)
        if not lines:
            logger.warning(f"项目没有台词: id={project_id}")
            raise HTTPException(status_code=400, detail="项目没有台词，请先解析文本")
        
        # 获取所有角色
        characters = db.get_project_characters(project_id)
        character_map = {char.id: char for char in characters}
        
        # 获取音频生成器
        generator = get_audio_generator()
        
        # 生成音频
        db.update_project_status(project_id, "generating")
        
        audio_segments = []
        for line in lines:
            if line.character_id and line.character_id in character_map:
                char = character_map[line.character_id]
                if char.voice_id:
                    voice = db.get_voice(char.voice_id)
                    if voice:
                        voice_config = VoiceConfig(
                            id=voice.id,
                            name=voice.name,
                            voice_type=voice.voice_type,
                            speaker=voice.speaker,
                            instruct=voice.instruct,
                            ref_audio_path=voice.ref_audio_path,
                            ref_text=voice.ref_text
                        )
                        
                        try:
                            audio, sr = generator.generate_with_voice_config(line.content, voice_config)
                            output_path = f"static/audio/project_{project_id}_line_{line.id}.wav"
                            save_audio(audio, sr, output_path)
                            db.create_audio_segment(project_id, line.id, line.character_id, output_path)
                            audio_segments.append((audio, sr))
                        except Exception as e:
                            logger.error(f"生成第 {line.id} 行音频失败: {e}")
        
        # 合并音频
        if audio_segments:
            output_path = f"static/audio/project_{project_id}_merged.wav"
            merge_audio_segments(audio_segments, output_path)
        
        db.update_project_status(project_id, "completed")
        
        duration = time.time() - start_time
        logger.info(f"项目音频生成完成: id={project_id}, 共 {len(audio_segments)} 段音频, 耗时: {duration:.2f}秒")
        
        return {"message": "音频生成完成", "segments_count": len(audio_segments)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成项目音频失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}/audio")
async def get_project_audio(project_id: int):
    """获取项目音频"""
    logger.info(f"获取项目音频: id={project_id}")
    
    try:
        segments = db.get_project_audio_segments(project_id)
        logger.info(f"获取音频成功: 共 {len(segments)} 段音频")
        return [{"id": s.id, "line_id": s.line_id, "character_id": s.character_id, "audio_path": s.audio_path, "duration": s.duration} for s in segments]
    except Exception as e:
        logger.error(f"获取项目音频失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}/download")
async def download_project_audio(project_id: int):
    """下载项目音频"""
    logger.info(f"下载项目音频: id={project_id}")
    
    try:
        audio_path = f"static/audio/project_{project_id}_merged.wav"
        if not os.path.exists(audio_path):
            logger.warning(f"音频文件不存在: {audio_path}")
            raise HTTPException(status_code=404, detail="音频文件不存在")
        logger.info(f"音频下载成功: {audio_path}")
        return FileResponse(audio_path, filename=f"project_{project_id}_audio.wav")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载项目音频失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 配置API ==========

@app.get("/api/config")
async def get_config():
    """获取系统配置"""
    logger.info("获取系统配置")
    
    try:
        return config.config
    except Exception as e:
        logger.error(f"获取配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/reload")
async def reload_config():
    """重新加载配置"""
    logger.info("重新加载配置")
    
    try:
        config.reload()
        logger.info("配置重新加载成功")
        return {"message": "配置已重新加载"}
    except Exception as e:
        logger.error(f"重新加载配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 日志API ==========

@app.get("/api/logs")
async def get_logs(lines: int = 100):
    """获取日志内容"""
    logger.info(f"获取日志: lines={lines}")
    
    try:
        log_file = "logs/novel_tts.log"
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                return {"logs": all_lines[-lines:]}
        return {"logs": []}
    except Exception as e:
        logger.error(f"获取日志失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== 前端页面 ==========

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """主页面"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>小说多角色语音合成系统</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
            .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            h1 { color: #333; }
            .section { margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 4px; }
            .btn { background: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; margin: 5px; }
            .btn:hover { background: #0056b3; }
            .btn-secondary { background: #6c757d; }
            .btn-success { background: #28a745; }
            .btn-danger { background: #dc3545; }
            textarea { width: 100%; height: 200px; margin: 10px 0; }
            table { width: 100%; border-collapse: collapse; margin: 10px 0; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f8f9fa; }
            .character-card { display: inline-block; margin: 5px; padding: 10px; border: 1px solid #ddd; border-radius: 4px; }
            .audio-player { margin: 10px 0; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>小说多角色语音合成系统</h1>
            
            <div class="section">
                <h2>1. 上传小说文本</h2>
                <textarea id="textContent" placeholder="请输入小说文本，支持 [角色名] 台词 格式..."></textarea>
                <br>
                <input type="text" id="projectName" placeholder="项目名称" value="我的小说">
                <button class="btn" onclick="createProject()">创建项目</button>
            </div>
            
            <div class="section">
                <h2>2. 项目管理</h2>
                <button class="btn btn-secondary" onclick="loadProjects()">刷新项目列表</button>
                <div id="projectsList"></div>
            </div>
            
            <div class="section">
                <h2>3. 声音库管理</h2>
                <button class="btn btn-secondary" onclick="loadVoices()">刷新声音列表</button>
                <div id="voicesList"></div>
            </div>
            
            <div class="section">
                <h2>4. 音频生成</h2>
                <div id="generateSection">
                    <p>请先选择项目并解析文本</p>
                </div>
            </div>
        </div>
        
        <script>
            let currentProjectId = null;
            
            async function createProject() {
                const name = document.getElementById('projectName').value;
                const textContent = document.getElementById('textContent').value;
                
                if (!name || !textContent) {
                    alert('请输入项目名称和文本内容');
                    return;
                }
                
                const formData = new FormData();
                formData.append('name', name);
                formData.append('text_content', textContent);
                
                try {
                    const response = await fetch('/api/projects', {
                        method: 'POST',
                        body: formData
                    });
                    const result = await response.json();
                    alert('项目创建成功！ID: ' + result.id);
                    loadProjects();
                } catch (error) {
                    alert('创建项目失败: ' + error);
                }
            }
            
            async function loadProjects() {
                try {
                    const response = await fetch('/api/projects');
                    const projects = await response.json();
                    displayProjects(projects);
                } catch (error) {
                    console.error('加载项目失败:', error);
                }
            }
            
            function displayProjects(projects) {
                const container = document.getElementById('projectsList');
                if (projects.length === 0) {
                    container.innerHTML = '<p>暂无项目</p>';
                    return;
                }
                
                let html = '<table><tr><th>ID</th><th>名称</th><th>状态</th><th>操作</th></tr>';
                projects.forEach(project => {
                    html += `<tr>
                        <td>${project.id}</td>
                        <td>${project.name}</td>
                        <td>${project.status}</td>
                        <td>
                            <button class="btn btn-secondary" onclick="parseProject(${project.id})">解析</button>
                            <button class="btn btn-success" onclick="generateAudio(${project.id})">生成音频</button>
                            <button class="btn btn-danger" onclick="deleteProject(${project.id})">删除</button>
                        </td>
                    </tr>`;
                });
                html += '</table>';
                container.innerHTML = html;
            }
            
            async function parseProject(projectId) {
                try {
                    const response = await fetch(`/api/projects/${projectId}/parse`, {
                        method: 'POST'
                    });
                    const result = await response.json();
                    alert(`解析完成！角色: ${result.characters.join(', ')}, 台词数: ${result.lines_count}`);
                } catch (error) {
                    alert('解析失败: ' + error);
                }
            }
            
            async function generateAudio(projectId) {
                try {
                    const response = await fetch(`/api/projects/${projectId}/generate`, {
                        method: 'POST'
                    });
                    const result = await response.json();
                    alert('音频生成完成！');
                } catch (error) {
                    alert('生成音频失败: ' + error);
                }
            }
            
            async function deleteProject(projectId) {
                if (!confirm('确定要删除这个项目吗？')) return;
                
                try {
                    await fetch(`/api/projects/${projectId}`, {
                        method: 'DELETE'
                    });
                    loadProjects();
                } catch (error) {
                    alert('删除失败: ' + error);
                }
            }
            
            async function loadVoices() {
                try {
                    const response = await fetch('/api/voices');
                    const voices = await response.json();
                    displayVoices(voices);
                } catch (error) {
                    console.error('加载声音失败:', error);
                }
            }
            
            function displayVoices(voices) {
                const container = document.getElementById('voicesList');
                if (voices.length === 0) {
                    container.innerHTML = '<p>暂无声音</p>';
                    return;
                }
                
                let html = '<table><tr><th>ID</th><th>名称</th><th>类型</th><th>描述</th></tr>';
                voices.forEach(voice => {
                    html += `<tr>
                        <td>${voice.id}</td>
                        <td>${voice.name}</td>
                        <td>${voice.type}</td>
                        <td>${voice.description || '无'}</td>
                    </tr>`;
                });
                html += '</table>';
                container.innerHTML = html;
            }
            
            // 页面加载时初始化
            document.addEventListener('DOMContentLoaded', function() {
                loadProjects();
                loadVoices();
            });
        </script>
    </body>
    </html>
    """


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
