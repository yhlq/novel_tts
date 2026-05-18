import logging
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Optional
import traceback


class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器"""
    
    # 颜色代码
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',     # 红色
        'CRITICAL': '\033[35m',   # 紫色
    }
    RESET = '\033[0m'
    
    def format(self, record):
        # 添加颜色
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        
        # 格式化时间
        record.asctime = self.formatTime(record)
        
        return super().format(record)


def setup_logger(
    name: str = "novel_tts",
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    console_output: bool = True,
    file_output: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> logging.Logger:
    """
    设置日志记录器
    
    Args:
        name: 日志记录器名称
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径
        console_output: 是否输出到控制台
        file_output: 是否输出到文件
        max_bytes: 单个日志文件最大大小
        backup_count: 备份文件数量
    
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # 清除已有的处理器
    logger.handlers.clear()
    
    # 日志格式
    log_format = '%(asctime)s [%(levelname)s] %(name)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # 控制台输出
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_formatter = ColoredFormatter(log_format, datefmt=date_format)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    # 文件输出
    if file_output:
        if log_file is None:
            # 默认日志文件
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            log_file = str(log_dir / f"{name}_{datetime.now().strftime('%Y%m%d')}.log")
        
        # 创建日志目录
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 使用 RotatingFileHandler 实现日志轮转
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(log_format, datefmt=date_format)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger


class LoggerMixin:
    """日志混入类，为类提供日志功能"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def log_info(self, message: str, **kwargs):
        """记录信息日志"""
        self.logger.info(message, extra=kwargs)
    
    def log_debug(self, message: str, **kwargs):
        """记录调试日志"""
        self.logger.debug(message, extra=kwargs)
    
    def log_warning(self, message: str, **kwargs):
        """记录警告日志"""
        self.logger.warning(message, extra=kwargs)
    
    def log_error(self, message: str, exception: Optional[Exception] = None, **kwargs):
        """记录错误日志"""
        if exception:
            self.logger.error(f"{message}: {str(exception)}\n{traceback.format_exc()}", extra=kwargs)
        else:
            self.logger.error(message, extra=kwargs)
    
    def log_critical(self, message: str, exception: Optional[Exception] = None, **kwargs):
        """记录严重错误日志"""
        if exception:
            self.logger.critical(f"{message}: {str(exception)}\n{traceback.format_exc()}", extra=kwargs)
        else:
            self.logger.critical(message, extra=kwargs)


# 全局日志记录器
logger = setup_logger()


def get_logger(name: str = "novel_tts") -> logging.Logger:
    """获取日志记录器"""
    return logging.getLogger(name)


def log_system_info():
    """记录系统信息"""
    import platform
    
    logger.info("=" * 50)
    logger.info("系统信息:")
    logger.info(f"  操作系统: {platform.system()} {platform.release()}")
    logger.info(f"  Python版本: {platform.python_version()}")
    
    # 尝试导入torch
    try:
        import torch
        logger.info(f"  PyTorch版本: {torch.__version__}")
        logger.info(f"  CUDA可用: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            logger.info(f"  CUDA版本: {torch.version.cuda}")
            logger.info(f"  GPU数量: {torch.cuda.device_count()}")
            for i in range(torch.cuda.device_count()):
                logger.info(f"  GPU {i}: {torch.cuda.get_device_name(i)}")
    except ImportError:
        logger.warning("  PyTorch未安装")
    
    logger.info("=" * 50)


def log_model_info(model_name: str, device: str, dtype: str):
    """记录模型信息"""
    logger.info(f"模型加载信息:")
    logger.info(f"  模型名称: {model_name}")
    logger.info(f"  设备: {device}")
    logger.info(f"  数据类型: {dtype}")


def log_generation_info(text: str, speaker: Optional[str] = None, 
                       language: str = "Chinese", duration: Optional[float] = None):
    """记录生成信息"""
    logger.info(f"音频生成信息:")
    logger.info(f"  文本长度: {len(text)} 字符")
    if speaker:
        logger.info(f"  说话人: {speaker}")
    logger.info(f"  语言: {language}")
    if duration:
        logger.info(f"  生成时长: {duration:.2f} 秒")


def log_performance_metrics(operation: str, duration: float, **kwargs):
    """记录性能指标"""
    logger.info(f"性能指标 - {operation}:")
    logger.info(f"  耗时: {duration:.2f} 秒")
    for key, value in kwargs.items():
        logger.info(f"  {key}: {value}")


# 上下文管理器，用于记录操作时间
import time
from contextlib import contextmanager

@contextmanager
def log_time(operation: str, logger: Optional[logging.Logger] = None):
    """记录操作时间的上下文管理器"""
    log = logger or get_logger()
    start_time = time.time()
    log.info(f"开始 {operation}...")
    try:
        yield
    except Exception as e:
        log.error(f"{operation} 失败: {e}")
        raise
    finally:
        end_time = time.time()
        duration = end_time - start_time
        log.info(f"完成 {operation}，耗时: {duration:.2f} 秒")


# 装饰器，用于记录函数执行时间
def log_execution_time(func):
    """记录函数执行时间的装饰器"""
    def wrapper(*args, **kwargs):
        logger = get_logger()
        start_time = time.time()
        logger.debug(f"开始执行 {func.__name__}...")
        try:
            result = func(*args, **kwargs)
            end_time = time.time()
            duration = end_time - start_time
            logger.debug(f"完成 {func.__name__}，耗时: {duration:.2f} 秒")
            return result
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            logger.error(f"{func.__name__} 执行失败 (耗时: {duration:.2f} 秒): {e}")
            raise
    return wrapper